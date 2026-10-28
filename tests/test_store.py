import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from stockdesk.receipts import export_receipt
from stockdesk.store import Store, cents


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = Store(self.root / "inventory.sqlite")
        self.identifier = self.store.create_product(
            "sku-1", "Producto", 10, 15, stock=5, barcode="123456"
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_money_is_exact_and_rejects_fractional_cents(self):
        self.assertEqual(cents("0.29"), 29)
        for value in ["-1", "0.001", "NaN", "Infinity"]:
            with self.assertRaises(ValueError):
                cents(value)

    def test_sku_and_barcode_are_unique(self):
        with self.assertRaises(ValueError):
            self.store.create_product("SKU-1", "Other", 1, 2)
        with self.assertRaises(ValueError):
            self.store.create_product("sku-2", "Other", 1, 2, barcode="123456")

    def test_sale_snapshot_and_ledger(self):
        sale = self.store.sell([{"id": self.identifier, "quantity": 2}], "Cliente")
        row, lines = self.store.receipt(sale)
        self.assertEqual(row["total"], 3000)
        self.assertEqual(lines[0]["price"], 1500)
        self.assertEqual(self.store.products()[0]["stock"], 3)
        self.assertEqual(sum(row["delta"] for row in self.store.movements()), 3)

    def test_failed_multiline_sale_rolls_back_all_products(self):
        other = self.store.create_product("second", "Other", 1, 2, stock=0)
        with self.assertRaises(ValueError):
            self.store.sell([{"id": self.identifier, "quantity": 1}, {"id": other, "quantity": 1}])
        self.assertEqual(self.store.sales(), [])
        self.assertEqual(
            next(p for p in self.store.products() if p["id"] == self.identifier)["stock"], 5
        )

    def test_concurrent_sales_cannot_oversell(self):
        def buy():
            try:
                self.store.sell([{"id": self.identifier, "quantity": 4}])
                return True
            except ValueError:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: buy(), range(2)))
        self.assertEqual(sum(results), 1)
        self.assertEqual(self.store.products()[0]["stock"], 1)

    def test_cancellation_restores_only_once(self):
        sale = self.store.sell([{"id": self.identifier, "quantity": 2}])
        self.store.cancel(sale)
        with self.assertRaises(ValueError):
            self.store.cancel(sale)
        self.assertEqual(self.store.products()[0]["stock"], 5)

    def test_movement_cannot_make_stock_negative(self):
        with self.assertRaises(ValueError):
            self.store.move(self.identifier, -6, "Salida")
        self.store.move(self.identifier, 2, "Compra")
        self.assertEqual(self.store.products()[0]["stock"], 7)

    def test_currency_locks_after_first_product(self):
        with self.assertRaises(ValueError):
            self.store.currency("USD")
        self.assertEqual(self.store.currency(), "PEN")

    def test_backup_is_consistent_and_does_not_overwrite(self):
        path = self.root / "backup.sqlite"
        self.store.backup(path)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(db.execute("SELECT count(*) FROM products").fetchone()[0], 1)
        with self.assertRaises(ValueError):
            self.store.backup(path)

    def test_real_pdf_receipt(self):
        sale = self.store.sell([{"id": self.identifier, "quantity": 1}])
        path = self.root / "receipt.pdf"
        export_receipt(self.store, sale, path)
        self.assertTrue(path.read_bytes().startswith(b"%PDF"))
        self.assertGreater(path.stat().st_size, 1000)
