import unittest
from datetime import date

from app.helpers.accounts_ui import enrich_account_row, holdings_kpis
from app.helpers.loan_math import apply_emi_cycle, loan_certificate, next_emi_date, suggested_emi, suggested_tenure


class TestLoanMath(unittest.TestCase):
    def test_interest_added_then_emi_splits(self):
        split = apply_emi_cycle(outstanding=840000, emi_amount=85000, annual_rate=8.4)
        self.assertEqual(split["interest"], 5880.00)
        self.assertEqual(split["principal"], 79120.00)
        self.assertEqual(split["payment"], 85000.00)
        self.assertEqual(split["outstanding"], 760880.00)

    def test_final_payment_closes_loan(self):
        split = apply_emi_cycle(outstanding=1000, emi_amount=5000, annual_rate=12)
        self.assertTrue(split["closed"])
        self.assertEqual(split["outstanding"], 0)
        self.assertEqual(split["interest"], 10.00)
        self.assertEqual(split["principal"], 1000.00)
        self.assertEqual(split["payment"], 1010.00)

    def test_next_emi_clamps_month_end(self):
        self.assertEqual(next_emi_date(date(2026, 1, 31), 31, inclusive=False), date(2026, 2, 28))

    def test_certificate_totals(self):
        cert = loan_certificate(
            {
                "original_principal": 840000,
                "balance": 760880,
                "interest_paid": 5880,
                "principal_paid": 79120,
                "emis_paid": 1,
                "interest_rate": 8.4,
                "emi_amount": 85000,
            }
        )
        self.assertEqual(cert["total_paid"], 85000)
        self.assertEqual(cert["interest_paid"], 5880)
        self.assertEqual(cert["principal_paid"], 79120)

    def test_holdings_kpis_exclude_loan_from_cash(self):
        rows = [
            enrich_account_row({"_id": "1", "name": "ICICI", "type": "current", "balance": 187108, "bank_name": "ICICI"}),
            enrich_account_row({"_id": "2", "name": "HDFC Home Loan", "type": "loan", "balance": 840000, "bank_name": "HDFC", "interest_rate": 8.4, "emi_amount": 85000}),
        ]
        kpis = holdings_kpis(rows)
        self.assertEqual(kpis["total_cash"], 187108)
        self.assertEqual(kpis["loans_outstanding"], 840000)

    def test_suggested_emi_positive(self):
        emi = suggested_emi(840000, 8.4, 120)
        self.assertGreater(emi, 0)
        self.assertLess(emi, 840000)

    def test_suggested_tenure_round_trips_emi(self):
        emi = suggested_emi(840000, 8.4, 120)
        self.assertAlmostEqual(suggested_tenure(840000, 8.4, emi), 120, delta=1)
        self.assertEqual(suggested_tenure(120000, 0, 10000), 12)

    def test_loan_kind_drives_icon_and_label(self):
        inferred = enrich_account_row({"_id": "2", "name": "HDFC Home Loan", "type": "loan", "balance": 1, "bank_name": "HDFC"})
        personal = enrich_account_row({"_id": "3", "name": "ICICI Personal Loan", "type": "loan", "balance": 1, "bank_name": "ICICI", "loan_kind": "personal"})
        misfiled = enrich_account_row({"_id": "4", "name": "ICICI Personal Loan", "type": "loan", "balance": 1, "bank_name": "ICICI", "loan_kind": "home"})
        self.assertEqual(inferred["loan_kind"], "home")
        self.assertEqual(inferred["type_icon"], "fa-house-chimney")
        self.assertEqual(personal["loan_kind"], "personal")
        self.assertEqual(personal["type_label"], "Personal Loan")
        self.assertEqual(personal["type_icon"], "fa-user")
        self.assertEqual(misfiled["loan_kind"], "personal")
        self.assertEqual(misfiled["type_icon"], "fa-user")
        self.assertEqual(personal["amount_kind"], "liability")
        self.assertEqual(personal["status_label"], "On track")

    def test_card_status_keeps_utilization_separate(self):
        row = enrich_account_row({
            "_id": "c1",
            "name": "Kotak Credit Card",
            "type": "credit_card",
            "bank_name": "Kotak",
            "credit_limit": 100000,
            "balance": -4700,
        })
        self.assertEqual(row["status_label"], "Healthy")
        self.assertEqual(row["utilization"], 4.7)
        self.assertFalse(row["row_alert"])
        self.assertEqual(row["amount_kind"], "liability")

    def test_account_mask_uses_last4_or_star(self):
        blank = enrich_account_row({"_id": "abc123", "name": "ICICI", "type": "current", "balance": 100, "bank_name": "ICICI"})
        filled = enrich_account_row({"_id": "abc123", "name": "ICICI", "type": "current", "balance": 100, "bank_name": "ICICI", "last4": "0821"})
        self.assertEqual(blank["mask"], "*")
        self.assertEqual(filled["mask"], "•• 0821")
        self.assertEqual(blank["brand_key"], "icici")
        self.assertIn("icici.svg", blank["logo_url"])


if __name__ == "__main__":
    unittest.main()
