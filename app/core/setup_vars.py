DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"   # TEMP / ONE-TIME
DEFAULT_EMAIL_ADDRESS = "admin@example.com"

SYSTEM_CATEGORIES = [
    # =====================
    # INCOME
    # =====================
    {
        "type": "credit",
        "code": "income",
        "name": "Income",
        "is_system": True,
        "categories": [
            {
                "code": "salary",
                "name": "Salary",
                "subcategories": [
                    {"code": "monthly_salary", "name": "Monthly Salary"},
                    {"code": "bonus", "name": "Bonus"},
                    {"code": "freelance", "name": "Freelance"},
                ],
            },
            {
                "code": "investments_income",
                "name": "Investments",
                "subcategories": [
                    {"code": "stocks", "name": "Stocks"},
                    {"code": "mutual_funds", "name": "Mutual Funds"},
                    {"code": "dividends", "name": "Dividends"},
                    {"code": "redemption", "name": "Redemption"},
                ],
            },
            {
                "code": "other_income",
                "name": "Other",
                "subcategories": [
                    {"code": "gifts", "name": "Gifts"},
                    {"code": "rental_income", "name": "Rental Income"},
                    {"code": "interest_income", "name": "Interest Income"},
                    {"code": "others", "name": "Others"},
                ],
            },
        ],
    },

    # =====================
    # EXPENSE
    # =====================
    {
        "type": "debit",
        "code": "expense",
        "name": "Expense",
        "is_system": True,
        "categories": [
            {
                "code": "food",
                "name": "Food",
                "subcategories": [
                    {"code": "groceries", "name": "Groceries"},
                    {"code": "dining_out", "name": "Dining Out"},
                    {"code": "snacks", "name": "Snacks"},
                ],
            },
            {
                "code": "utilities",
                "name": "Utilities",
                "subcategories": [
                    {"code": "electricity", "name": "Electricity"},
                    {"code": "water", "name": "Water"},
                    {"code": "internet", "name": "Internet"},
                    {"code": "gas", "name": "Gas"},
                    {"code": "creditcard", "name": "Credit Card"},
                    {"code": "mobile", "name": "Mobile Recharge"},
                ],
            },
            {
                "code": "housing",
                "name": "Housing",
                "subcategories": [
                    {"code": "rent", "name": "Rent"},
                    {"code": "maintenance", "name": "Maintenance"},
                    {"code": "property_tax", "name": "Property Tax"},
                    {"code": "maid", "name": "Maid Salary"},
                ],
            },
            {
                "code": "investments_expense",
                "name": "Investment",
                "subcategories": [
                    {"code": "sip", "name": "SIP"},
                    {"code": "stocks", "name": "Stocks"},
                    {"code": "savings", "name": "Savings"},
                    {"code": "fixed_deposit", "name": "Fixed Deposit"},
                    {"code": "recurring_deposit", "name": "Recurring Deposit"},
                    {"code": "mutual_funds", "name": "Mutual Funds"},
                    {"code": "crypto", "name": "Crypto"},
                    {"code": "gold", "name": "Gold"},
                    {"code": "bonds", "name": "Bonds"},
                    {"code": "others", "name": "Others"},
                ],
            },
            {
                "code": "loan",
                "name": "Loan",
                "subcategories": [
                    {"code": "home_loan", "name": "Home Loan"},
                    {"code": "personal_loan", "name": "Personal Loan"},
                    {"code": "gold_loan", "name": "Gold Loan"},
                    {"code": "car_loan", "name": "Car Loan"},
                    {"code": "education_loan", "name": "Education Loan"},
                    {"code": "interest_payment", "name": "Interest Payment"},
                    {"code": "other_loans", "name": "Other Loans"},
                ],
            },
            {
                "code": "transport",
                "name": "Transport",
                "subcategories": [
                    {"code": "fuel", "name": "Fuel"},
                    {"code": "public_transport", "name": "Public Transport"},
                    {"code": "taxi", "name": "Taxi"},
                ],
            },
            {
                "code": "health",
                "name": "Health",
                "subcategories": [
                    {"code": "medicines", "name": "Medicines"},
                    {"code": "doctor", "name": "Doctor"},
                    {"code": "insurance", "name": "Insurance"},
                ],
            },
            {
                "code": "education",
                "name": "Education",
                "subcategories": [
                    {"code": "tuition", "name": "Tuition"},
                    {"code": "books", "name": "Books"},
                    {"code": "courses", "name": "Courses"},
                ],
            },
            {
                "code": "entertainment",
                "name": "Entertainment",
                "subcategories": [
                    {"code": "movies", "name": "Movies"},
                    {"code": "subscriptions", "name": "Subscriptions"},
                    {"code": "travel", "name": "Travel"},
                ],
            },
            {
                "code": "shopping",
                "name": "Shopping",
                "subcategories": [
                    {"code": "clothing", "name": "Clothing"},
                    {"code": "electronics", "name": "Electronics"},
                    {"code": "other", "name": "Other"},
                ],
            },
            {
                "code": "others_expense",
                "name": "Others",
                "subcategories": [
                    {"code": "miscellaneous", "name": "Miscellaneous"},
                    {"code": "donations", "name": "Donations"},
                ],
            },
        ],
    },

    # =====================
    # SELF TRANSFER
    # =====================
    {
        "type": "transfer",
        "code": "self_transfer",
        "name": "Self Transfer",
        "is_system": True,
        "categories": [
            {
                "code": "bank_transfer",
                "name": "Bank Transfers",
                "subcategories": [
                    {"code": "to_savings", "name": "To Savings"},
                    {"code": "to_current", "name": "To Current"},
                ],
            },
            {
                "code": "wallet_transfer",
                "name": "Wallet Transfers",
                "subcategories": [
                    {"code": "paytm", "name": "To Paytm"},
                    {"code": "phonepe", "name": "To PhonePe"},
                    {"code": "gpay", "name": "To Google Pay"},
                ],
            },
            {
                "code": "investment_transfer",
                "name": "Investment",
                "subcategories": [
                    {"code": "sip", "name": "SIP"},
                    {"code": "lumpsum", "name": "Lumpsum"},
                    {"code": "emi_payment", "name": "EMI Payment"},
                ],
            },
            {
                "code": "loan_transfer",
                "name": "Loan",
                "subcategories": [
                    {"code": "emi_payment", "name": "EMI Payment"},
                    {"code": "loan_disbursement", "name": "Loan Disbursement"},
                ],
            },
        ],
    },
]
