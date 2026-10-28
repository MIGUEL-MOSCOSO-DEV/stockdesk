import sqlite3
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .database import connection


def cents(value):
    try:
        amount = Decimal(str(value))
        if (
            not amount.is_finite()
            or amount < 0
            or amount > Decimal("10000000")
            or amount != amount.quantize(Decimal(".01"))
        ):
            raise ValueError()
        return int(amount * 100)
    except (InvalidOperation, ValueError):
        raise ValueError("Usa un importe positivo con hasta dos decimales.") from None


def quantity(value, allow_zero=False):
    if type(value) is not int or value < (0 if allow_zero else 1) or value > 10000000:
        raise ValueError("La cantidad debe ser un entero válido.")
    return value


class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                INSERT OR IGNORE INTO settings VALUES('currency','PEN');
                CREATE TABLE IF NOT EXISTS products(id TEXT PRIMARY KEY,sku TEXT UNIQUE NOT NULL,barcode TEXT UNIQUE,name TEXT NOT NULL,category TEXT NOT NULL,cost INTEGER NOT NULL,price INTEGER NOT NULL,stock INTEGER NOT NULL CHECK(stock>=0),minimum INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS sales(id TEXT PRIMARY KEY,customer TEXT NOT NULL,total INTEGER NOT NULL,currency TEXT NOT NULL,created REAL NOT NULL,cancelled INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS sale_lines(sale_id TEXT REFERENCES sales(id),product_id TEXT REFERENCES products(id),sku TEXT,name TEXT,quantity INTEGER,cost INTEGER,price INTEGER);
                CREATE TABLE IF NOT EXISTS movements(id INTEGER PRIMARY KEY,product_id TEXT REFERENCES products(id),delta INTEGER NOT NULL,balance INTEGER NOT NULL,reason TEXT NOT NULL,created REAL NOT NULL);
                PRAGMA user_version=1;
            """)

    def connect(self):
        return connection(self.path)

    def currency(self, value=None):
        with self.connect() as db:
            if value is not None:
                db.execute("BEGIN IMMEDIATE")
                if value not in ["PEN", "USD", "EUR", "MXN", "COP"]:
                    raise ValueError("Moneda no admitida.")
                if db.execute("SELECT 1 FROM products LIMIT 1").fetchone():
                    raise ValueError("La moneda queda fija desde el primer producto.")
                db.execute("UPDATE settings SET value=? WHERE key='currency'", (value,))
            return db.execute("SELECT value FROM settings WHERE key='currency'").fetchone()[0]

    def create_product(self, sku, name, cost, price, stock=0, minimum=0, barcode="", category=""):
        sku, name = sku.strip().upper(), name.strip()
        if (
            not sku
            or len(sku) > 80
            or not name
            or len(name) > 160
            or len(barcode) > 100
            or len(category) > 100
        ):
            raise ValueError("Revisa SKU, nombre y longitud de los campos.")
        cost, price = cents(cost), cents(price)
        quantity(stock, True)
        quantity(minimum, True)
        identifier = uuid.uuid4().hex
        try:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT INTO products VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        identifier,
                        sku,
                        barcode.strip() or None,
                        name,
                        category.strip(),
                        cost,
                        price,
                        stock,
                        minimum,
                    ),
                )
                if stock:
                    db.execute(
                        "INSERT INTO movements(product_id,delta,balance,reason,created) VALUES(?,?,?,?,?)",
                        (identifier, stock, stock, "Saldo inicial", time.time()),
                    )
        except sqlite3.IntegrityError:
            raise ValueError("El SKU o código de barras ya existe.") from None
        return identifier

    def products(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM products ORDER BY name")]

    def move(self, identifier, delta, reason):
        if (
            type(delta) is not int
            or not delta
            or abs(delta) > 10000000
            or not reason.strip()
            or len(reason) > 300
        ):
            raise ValueError("Indica un movimiento y su motivo.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM products WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise ValueError("Producto no encontrado.")
            balance = row["stock"] + delta
            if balance < 0 or balance > 10000000:
                raise ValueError("El movimiento deja un saldo fuera de rango.")
            db.execute("UPDATE products SET stock=? WHERE id=?", (balance, identifier))
            db.execute(
                "INSERT INTO movements(product_id,delta,balance,reason,created) VALUES(?,?,?,?,?)",
                (identifier, delta, balance, reason.strip(), time.time()),
            )

    def sell(self, items, customer=""):
        if not items or len(items) > 100 or len(customer) > 160:
            raise ValueError("La venta necesita de 1 a 100 productos.")
        if len({item["id"] for item in items}) != len(items):
            raise ValueError("Agrupa las unidades de cada producto en una sola línea.")
        identifier = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            lines = []
            for item in items:
                count = quantity(item["quantity"])
                row = db.execute("SELECT * FROM products WHERE id=?", (item["id"],)).fetchone()
                if not row or row["stock"] < count:
                    raise ValueError("No hay existencias suficientes para toda la venta.")
                lines.append((row, count))
            total = sum(row["price"] * count for row, count in lines)
            currency = db.execute("SELECT value FROM settings WHERE key='currency'").fetchone()[0]
            db.execute(
                "INSERT INTO sales(id,customer,total,currency,created) VALUES(?,?,?,?,?)",
                (identifier, customer.strip(), total, currency, time.time()),
            )
            for row, count in lines:
                db.execute(
                    "INSERT INTO sale_lines VALUES(?,?,?,?,?,?,?)",
                    (
                        identifier,
                        row["id"],
                        row["sku"],
                        row["name"],
                        count,
                        row["cost"],
                        row["price"],
                    ),
                )
                db.execute("UPDATE products SET stock=stock-? WHERE id=?", (count, row["id"]))
                db.execute(
                    "INSERT INTO movements(product_id,delta,balance,reason,created) VALUES(?,?,?,?,?)",
                    (
                        row["id"],
                        -count,
                        row["stock"] - count,
                        "Venta " + identifier[:8],
                        time.time(),
                    ),
                )
        return identifier

    def cancel(self, identifier):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            sale = db.execute("SELECT * FROM sales WHERE id=?", (identifier,)).fetchone()
            if not sale or sale["cancelled"]:
                raise ValueError("La venta no existe o ya fue anulada.")
            for line in db.execute(
                "SELECT * FROM sale_lines WHERE sale_id=?", (identifier,)
            ).fetchall():
                db.execute(
                    "UPDATE products SET stock=stock+? WHERE id=?",
                    (line["quantity"], line["product_id"]),
                )
                balance = db.execute(
                    "SELECT stock FROM products WHERE id=?", (line["product_id"],)
                ).fetchone()[0]
                db.execute(
                    "INSERT INTO movements(product_id,delta,balance,reason,created) VALUES(?,?,?,?,?)",
                    (
                        line["product_id"],
                        line["quantity"],
                        balance,
                        "Anulación " + identifier[:8],
                        time.time(),
                    ),
                )
            db.execute("UPDATE sales SET cancelled=1 WHERE id=?", (identifier,))

    def sales(self):
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute("SELECT * FROM sales ORDER BY created DESC LIMIT 500")
            ]

    def receipt(self, identifier):
        with self.connect() as db:
            row = db.execute("SELECT * FROM sales WHERE id=?", (identifier,)).fetchone()
            if not row:
                raise ValueError("Venta no encontrada.")
            return dict(row), [
                dict(item)
                for item in db.execute("SELECT * FROM sale_lines WHERE sale_id=?", (identifier,))
            ]

    def movements(self):
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT movements.*,products.sku FROM movements JOIN products ON products.id=movements.product_id ORDER BY movements.id DESC LIMIT 1000"
                )
            ]

    def backup(self, path):
        path = Path(path).resolve()
        if path == self.path or path.exists():
            raise ValueError("Elige un archivo nuevo para la copia de seguridad.")
        with self.connect() as source, connection(path) as target:
            source.backup(target)
        return path
