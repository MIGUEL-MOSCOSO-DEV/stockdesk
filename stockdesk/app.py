import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, simpledialog, ttk

from .paths import data_dir
from .receipts import export_receipt
from .store import Store
from .ui import field, table, theme


class StockDesk:
    def __init__(self, root):
        self.root = root
        root.title("StockDesk — Inventario sin conexión")
        root.geometry("1160x780")
        theme(root, "#f4f6f8", "#243742", "#a9d1ed")
        self.store = Store(data_dir() / "inventory.sqlite")
        header = ttk.Frame(root, padding=24)
        header.pack(fill="x")
        ttk.Label(header, text="STOCKDESK", font=("Segoe UI", 26, "bold")).pack(side="left")
        ttk.Label(header, text="OPERACIÓN LOCAL / SIN CONEXIÓN", style="Sub.TLabel").pack(
            side="left", padx=22
        )
        ttk.Button(header, text="Copia de seguridad", command=self.backup).pack(side="right")
        ttk.Button(header, text="Moneda", command=self.currency).pack(side="right", padx=8)
        self.summary = tk.StringVar()
        ttk.Label(root, textvariable=self.summary, padding=(24, 10), font=("Consolas", 14)).pack(
            anchor="w"
        )
        book = ttk.Notebook(root)
        book.pack(fill="both", expand=True, padx=24, pady=16)
        self.inventory = ttk.Frame(book, padding=16)
        self.checkout = ttk.Frame(book, padding=16)
        self.ledger = ttk.Frame(book, padding=16)
        self.history = ttk.Frame(book, padding=16)
        for frame, name in [
            (self.inventory, "Catálogo"),
            (self.checkout, "Punto de registro"),
            (self.ledger, "Movimientos"),
            (self.history, "Ventas"),
        ]:
            book.add(frame, text=name)
        tools = ttk.Frame(self.inventory)
        tools.pack(fill="x")
        ttk.Button(tools, text="Añadir producto", command=self.product).pack(side="left")
        ttk.Button(tools, text="Entrada / salida", command=self.movement).pack(side="left", padx=8)
        self.query = tk.StringVar()
        ttk.Entry(tools, textvariable=self.query).pack(side="right")
        ttk.Label(tools, text="Buscar").pack(side="right", padx=8)
        self.query.trace_add("write", lambda *_: self.refresh_products())
        self.products_tree = table(
            self.inventory,
            ("SKU", "Producto", "Código", "Stock", "Mínimo", "Precio"),
            (130, 300, 160, 90, 90, 120),
        )
        bar = ttk.Frame(self.checkout)
        bar.pack(fill="x")
        ttk.Label(bar, text="Escanea un código o escribe un SKU y pulsa Enter").pack(anchor="w")
        self.scan = tk.StringVar()
        entry = ttk.Entry(bar, textvariable=self.scan, font=("Consolas", 16))
        entry.pack(fill="x", pady=10)
        entry.bind("<Return>", self.add_scan)
        self.cart = {}
        self.cart_tree = table(
            self.checkout, ("SKU", "Producto", "Unidades", "Subtotal"), (150, 420, 130, 160)
        )
        sale_tools = ttk.Frame(self.checkout)
        sale_tools.pack(fill="x")
        self.customer = tk.StringVar()
        ttk.Label(sale_tools, text="Cliente opcional").pack(side="left")
        ttk.Entry(sale_tools, textvariable=self.customer).pack(side="left", padx=10)
        ttk.Button(sale_tools, text="Quitar seleccionado", command=self.remove_line).pack(
            side="left", padx=8
        )
        self.total = tk.StringVar(value="TOTAL 0.00")
        ttk.Label(sale_tools, textvariable=self.total, font=("Consolas", 14, "bold")).pack(
            side="right"
        )
        ttk.Button(self.checkout, text="Registrar venta", command=self.sell).pack(
            anchor="e", pady=16
        )
        self.movements_tree = table(
            self.ledger, ("Fecha", "SKU", "Cambio", "Saldo", "Motivo"), (160, 140, 90, 90, 400)
        )
        self.sales_tree = table(
            self.history, ("Fecha", "Cliente", "Total", "Estado"), (170, 360, 160, 160)
        )
        actions = ttk.Frame(self.history)
        actions.pack(fill="x")
        ttk.Button(actions, text="Exportar recibo PDF", command=self.receipt).pack(side="left")
        ttk.Button(actions, text="Anular venta", command=self.cancel).pack(side="right")
        self.status = tk.StringVar(
            value="Listo. El lector de códigos funciona como teclado USB; no necesita controladores propios."
        )
        ttk.Label(root, textvariable=self.status, padding=16).pack(
            side="bottom", fill="x", before=book
        )
        self.refresh()

    def safe(self, work):
        try:
            result = work()
            self.refresh()
            return result
        except Exception as error:
            messagebox.showerror("Revisar operación", str(error), parent=self.root)

    def refresh_products(self):
        self.products_tree.delete(*self.products_tree.get_children())
        query = self.query.get().casefold()
        for p in self.store.products():
            if query in (p["sku"] + p["name"] + (p["barcode"] or "")).casefold():
                self.products_tree.insert(
                    "",
                    "end",
                    iid=p["id"],
                    values=(
                        p["sku"],
                        p["name"],
                        p["barcode"] or "—",
                        p["stock"],
                        p["minimum"],
                        f"{p['price'] / 100:.2f}",
                    ),
                )

    def refresh(self):
        products = self.store.products()
        self.summary.set(
            f"{len(products)} REFERENCIAS     {sum(p['stock'] for p in products)} UNIDADES     {sum(p['stock'] <= p['minimum'] for p in products)} BAJO MÍNIMO     {self.store.currency()}"
        )
        self.refresh_products()
        self.movements_tree.delete(*self.movements_tree.get_children())
        for row in self.store.movements():
            self.movements_tree.insert(
                "",
                "end",
                values=(
                    datetime.fromtimestamp(row["created"]).strftime("%d/%m %H:%M"),
                    row["sku"],
                    row["delta"],
                    row["balance"],
                    row["reason"],
                ),
            )
        self.sales_tree.delete(*self.sales_tree.get_children())
        for row in self.store.sales():
            self.sales_tree.insert(
                "",
                "end",
                iid=row["id"],
                values=(
                    datetime.fromtimestamp(row["created"]).strftime("%d/%m %H:%M"),
                    row["customer"] or "Sin nombre",
                    f"{row['total'] / 100:.2f} {row['currency']}",
                    "Anulada" if row["cancelled"] else "Registrada",
                ),
            )

    def product(self):
        window = tk.Toplevel(self.root)
        window.title("Nuevo producto")
        window.geometry("460x680")
        window.transient(self.root)
        panel = ttk.Frame(window, padding=24)
        panel.pack(fill="both", expand=True)
        fields = {
            key: field(panel, label, default)
            for key, label, default in [
                ("sku", "SKU", ""),
                ("name", "Nombre", ""),
                ("barcode", "Código de barras opcional", ""),
                ("category", "Categoría", ""),
                ("cost", "Costo unitario", ""),
                ("price", "Precio unitario", ""),
                ("stock", "Existencia inicial", "0"),
                ("minimum", "Stock mínimo", "0"),
            ]
        }

        def save():
            def work():
                values = {key: value.get() for key, value in fields.items()}
                values["stock"] = int(values["stock"])
                values["minimum"] = int(values["minimum"])
                self.store.create_product(**values)
                window.destroy()

            self.safe(work)

        ttk.Button(panel, text="Guardar producto", command=save).pack(fill="x", pady=20)
        window.grab_set()

    def movement(self):
        selected = self.products_tree.selection()
        if not selected:
            messagebox.showinfo("Producto", "Selecciona un producto del catálogo.")
            return
        amount = simpledialog.askinteger(
            "Movimiento",
            "Unidades: positivas para entrada; negativas para salida",
            parent=self.root,
        )
        if amount is None:
            return
        reason = simpledialog.askstring(
            "Motivo", "Describe la compra, salida o corrección", parent=self.root
        )
        if reason:
            self.safe(lambda: self.store.move(selected[0], amount, reason))

    def add_scan(self, event=None):
        query = self.scan.get().strip()
        item = next(
            (
                p
                for p in self.store.products()
                if p["sku"] == query.upper() or p["barcode"] == query
            ),
            None,
        )
        if not item:
            self.status.set("Código no encontrado en el catálogo.")
            return
        count = self.cart.get(item["id"], {}).get("quantity", 0) + 1
        if count > item["stock"]:
            self.status.set("No quedan unidades suficientes para añadir otra.")
            return
        self.cart[item["id"]] = {"product": item, "quantity": count}
        self.scan.set("")
        self.refresh_cart()

    def refresh_cart(self):
        self.cart_tree.delete(*self.cart_tree.get_children())
        total = 0
        for identifier, line in self.cart.items():
            p = line["product"]
            amount = p["price"] * line["quantity"]
            total += amount
            self.cart_tree.insert(
                "",
                "end",
                iid=identifier,
                values=(p["sku"], p["name"], line["quantity"], f"{amount / 100:.2f}"),
            )
        self.total.set(f"TOTAL {total / 100:.2f} {self.store.currency()}")

    def remove_line(self):
        selected = self.cart_tree.selection()
        if selected:
            self.cart.pop(selected[0], None)
            self.refresh_cart()

    def sell(self):
        def work():
            identifier = self.store.sell(
                [{"id": key, "quantity": value["quantity"]} for key, value in self.cart.items()],
                self.customer.get(),
            )
            self.cart.clear()
            self.customer.set("")
            self.refresh_cart()
            self.status.set(
                "Venta registrada: " + identifier[:8] + ". Puedes exportar su recibo desde Ventas."
            )

        self.safe(work)

    def cancel(self):
        selected = self.sales_tree.selection()
        if selected and messagebox.askyesno(
            "Anular venta", "Se devolverán las unidades al inventario. ¿Continuar?"
        ):
            self.safe(lambda: self.store.cancel(selected[0]))

    def receipt(self):
        selected = self.sales_tree.selection()
        if selected:
            path = filedialog.asksaveasfilename(
                defaultextension=".pdf", filetypes=[("PDF", "*.pdf")]
            )
            if path:
                self.safe(lambda: export_receipt(self.store, selected[0], path))

    def backup(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".sqlite", filetypes=[("SQLite", "*.sqlite")]
        )
        if path:
            self.safe(lambda: self.store.backup(path))
            self.status.set("Solicitud de copia finalizada. Revisa cualquier aviso mostrado.")

    def currency(self):
        value = simpledialog.askstring(
            "Moneda",
            "PEN, USD, EUR, MXN o COP. Solo antes del primer producto.",
            initialvalue=self.store.currency(),
            parent=self.root,
        )
        if value:
            self.safe(lambda: self.store.currency(value.strip().upper()))


def main():
    root = tk.Tk()
    StockDesk(root)
    root.mainloop()
