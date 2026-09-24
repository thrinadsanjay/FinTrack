import unittest

from app.utils.statement_narration_parser import parse_narration


class TestStatementNarrationParser(unittest.TestCase):
    def test_upi_dmart_reference(self):
        parsed = parse_narration("UPI/DR/736262/DMART BANGALORE/RefNo 736262")
        self.assertEqual(
            parsed,
            {
                "clean_description": "dmart bangalore",
                "merchant": "dmart",
                "location": "bangalore",
                "mode": "upi",
                "type_hint": "debit",
                "reference": "736262",
                "tokens": ["dmart", "bangalore"],
            },
        )

    def test_pos_card_amazon_pay(self):
        parsed = parse_narration("POS CARD TXN AMAZON PAY INDIA")
        self.assertEqual(parsed["clean_description"], "amazon pay")
        self.assertEqual(parsed["merchant"], "amazon")
        self.assertEqual(parsed["location"], "pay")
        self.assertEqual(parsed["mode"], "card")
        self.assertIsNone(parsed["type_hint"])
        self.assertIsNone(parsed["reference"])
        self.assertEqual(parsed["tokens"], ["amazon", "pay"])

    def test_neft_hdfc_life(self):
        parsed = parse_narration("NEFT TO HDFC LIFE INSURANCE CO LTD")
        self.assertEqual(parsed["clean_description"], "hdfc life insurance")
        self.assertEqual(parsed["merchant"], "hdfc")
        self.assertEqual(parsed["location"], "insurance")
        self.assertEqual(parsed["mode"], "transfer")
        self.assertEqual(parsed["tokens"], ["hdfc", "life", "insurance"])

    def test_imps_flipkart(self):
        parsed = parse_narration("IMPS-P2A-Flipkart Internet Private Limited")
        self.assertEqual(parsed["clean_description"], "flipkart internet")
        self.assertEqual(parsed["merchant"], "flipkart")
        self.assertEqual(parsed["location"], "internet")
        self.assertEqual(parsed["mode"], "transfer")
        self.assertEqual(parsed["tokens"], ["flipkart", "internet"])

    def test_upi_swiggy(self):
        parsed = parse_narration("UPI-SWIGGY-BANGALORE-KA")
        self.assertEqual(parsed["clean_description"], "swiggy bangalore ka")
        self.assertEqual(parsed["merchant"], "swiggy")
        self.assertEqual(parsed["location"], "ka")
        self.assertEqual(parsed["mode"], "upi")
        self.assertEqual(parsed["tokens"], ["swiggy", "bangalore", "ka"])

    def test_atm_cash_with_reference(self):
        parsed = parse_narration("ATM CASH WD 923456 MYSORE")
        self.assertEqual(parsed["merchant"], "cash")
        self.assertEqual(parsed["location"], "mysore")
        self.assertEqual(parsed["mode"], "cash")
        self.assertEqual(parsed["reference"], "923456")
        self.assertEqual(parsed["tokens"], ["cash", "wd", "mysore"])

    def test_upi_credit_refund(self):
        parsed = parse_narration("UPI/CR/998877/REFUND AMAZON/Ref 998877")
        self.assertEqual(parsed["mode"], "upi")
        self.assertEqual(parsed["type_hint"], "credit")
        self.assertEqual(parsed["reference"], "998877")
        self.assertEqual(parsed["tokens"], ["refund", "amazon"])
        self.assertEqual(parsed["clean_description"], "refund amazon")

    def test_card_restaurant_with_city(self):
        parsed = parse_narration("CARD TXN STARBUCKS MUMBAI")
        self.assertEqual(parsed["mode"], "card")
        self.assertEqual(parsed["merchant"], "starbucks")
        self.assertEqual(parsed["location"], "mumbai")
        self.assertEqual(parsed["clean_description"], "starbucks mumbai")

    def test_imps_vendor_with_number(self):
        parsed = parse_narration("IMPS/P2A/1234567890/ZEPTO/BANGALORE")
        self.assertEqual(parsed["mode"], "transfer")
        self.assertEqual(parsed["reference"], "1234567890")
        self.assertEqual(parsed["tokens"], ["zepto", "bangalore"])
        self.assertEqual(parsed["merchant"], "zepto")

    def test_neft_salary_credit(self):
        parsed = parse_narration("NEFT BY ACME TECHNOLOGIES SALARY")
        self.assertEqual(parsed["mode"], "transfer")
        self.assertEqual(parsed["clean_description"], "acme technologies salary")
        self.assertEqual(parsed["merchant"], "acme")
        self.assertEqual(parsed["location"], "salary")

    def test_comma_and_pipe_separators(self):
        parsed = parse_narration("UPI, DR, BIGBASKET | BENGALURU | Ref 11223344")
        self.assertEqual(parsed["mode"], "upi")
        self.assertEqual(parsed["type_hint"], "debit")
        self.assertEqual(parsed["reference"], "11223344")
        self.assertEqual(parsed["tokens"], ["bigbasket", "bengaluru"])
        self.assertEqual(parsed["clean_description"], "bigbasket bengaluru")

    def test_empty_narration(self):
        parsed = parse_narration("")
        self.assertEqual(
            parsed,
            {
                "clean_description": "",
                "merchant": None,
                "location": None,
                "mode": "unknown",
                "type_hint": None,
                "reference": None,
                "tokens": [],
            },
        )

    def test_numbers_only_become_empty_tokens(self):
        parsed = parse_narration("UPI/DR/123456/789012")
        self.assertEqual(parsed["mode"], "upi")
        self.assertEqual(parsed["type_hint"], "debit")
        self.assertEqual(parsed["reference"], "123456")
        self.assertEqual(parsed["tokens"], [])
        self.assertEqual(parsed["clean_description"], "")


if __name__ == "__main__":
    unittest.main()
