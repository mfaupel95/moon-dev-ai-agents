"""Offline regression: execute only the real validation method, never GUI imports."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class FiniteQuantityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[1] / "moongui.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))
        app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "App")
        method = next(n for n in app.body if isinstance(n, ast.FunctionDef) and n.name == "_send_order")
        # No module execution, credentials, sockets, processes, files or GUI widgets.
        cls.thread = Mock()
        cls.namespace = {"threading": SimpleNamespace(Thread=cls.thread),
                         "ORDER_LIMITS": {"OKX": .0002, "Kraken": .001, "Binance": .0005},
                         "okx_order": Mock(), "kraken_order": Mock(), "binance_order": Mock()}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), cls.namespace)

    def app(self, exchange, quantity):
        def var(value):
            return SimpleNamespace(get=lambda: value, set=Mock())
        return SimpleNamespace(exchange_var=var(exchange), arm_var=var(True),
                               order_inst=var("BTC-USDT"), order_side=var("buy"),
                               order_qty=var(quantity), order_key=var("synthetic"),
                               order_secret=var("synthetic"), order_pass=var("synthetic"),
                               boersen_log=None, _log=Mock(), _run_order=Mock())

    def test_nonfinite_quantities_never_create_order_thread(self):
        for exchange in self.namespace["ORDER_LIMITS"]:
            for quantity in ("nan", "NaN", "inf", "+inf", "-inf", "1e999"):
                with self.subTest(exchange=exchange, quantity=quantity):
                    self.thread.reset_mock()
                    app = self.app(exchange, quantity)
                    self.namespace["_send_order"](app)
                    self.thread.assert_not_called()
                    app._log.assert_called_once()

    def test_valid_quantity_keeps_existing_dispatch(self):
        for exchange in self.namespace["ORDER_LIMITS"]:
            with self.subTest(exchange=exchange):
                self.thread.reset_mock()
                self.namespace["_send_order"](self.app(exchange, "0.0001"))
                self.thread.assert_called_once()
                self.thread.return_value.start.assert_called_once()
                self.thread.return_value.start.reset_mock()


if __name__ == "__main__":
    unittest.main(verbosity=2)
