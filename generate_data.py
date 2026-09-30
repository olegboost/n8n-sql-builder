#!/usr/bin/env python3
"""
Скрипт наполнения БД clients_db вымышленными данными.

Заполняет 3 таблицы:
  - client_sociodem       (1 строка на клиента)
  - client_transactions   (несколько строк на клиента)
  - client_products       (несколько строк на клиента)

Все клиенты связаны полем clientbase — VARCHAR(6), ровно 6 символов
(латинские буквы и цифры), например 'K7Q2ZA'.

Использование:
    python generate_data.py --n-clients 100
    python generate_data.py --n-clients 1000000 --batch-size 50000

Для 1 млн клиентов скрипт использует потоковую загрузку через COPY
(psycopg2 copy_expert), что на порядок быстрее обычных INSERT.
"""

import argparse
import io
import random
import sys
import time
from datetime import date, datetime, timedelta

import numpy as np
import psycopg2
from faker import Faker

fake = Faker("ru_RU")
Faker.seed(42)
random.seed(42)
np.random.seed(42)

REGIONS = [
    "Минская область", "Брестская область", "Гомельская область",
    "Витебская область", "Гродненская область",
    "Могилевская область", "г. Минск",
]
CITIES_BY_REGION = {
    "Минская область": ["Минск", "Борисов", "Молодечно", "Солигорск"],
    "Брестская область": ["Брест", "Пинск", "Барановичи", "Кобрин"],
    "Гомельская область": ["Гомель", "Мозырь", "Жлобин", "Речица"],
    "Витебская область": ["Витебск", "Орша", "Полоцк", "Новополоцк"],
    "Гродненская область": ["Гродно", "Лида", "Слоним", "Волковыск"],
    "Могилевская область": ["Могилев", "Бобруйск", "Осиповичи", "Горки"],
    "г. Минск": ["Минск"],
}
EDUCATION = ["Среднее", "Среднее специальное", "Высшее", "Ученая степень"]
MARITAL = ["Холост/не замужем", "Женат/замужем", "Разведен(а)", "Вдовец/вдова"]
EMPLOYMENT = ["Наемный работник", "Индивидуальный предприниматель",
              "Пенсионер", "Студент", "Безработный", "Самозанятый"]
INCOME_SEGMENTS = ["LOW", "MEDIUM", "HIGH", "PREMIUM"]
INCOME_SEGMENT_WEIGHTS = [0.35, 0.40, 0.20, 0.05]
CURRENCIES = ["BYN", "USD", "EUR", "RUB"]
CURRENCY_WEIGHTS = [0.80, 0.10, 0.07, 0.03]
MCC_CATEGORIES = [
    (5411, "Продуктовые магазины"), (5812, "Рестораны"),
    (5541, "АЗС"), (4111, "Транспорт"), (5311, "Универмаги"),
    (5912, "Аптеки"), (4814, "Телеком"), (5732, "Электроника"),
    (5691, "Одежда"), (7011, "Отели"), (6011, "Снятие наличных"),
    (4900, "Коммунальные услуги"),
]
CHANNELS = ["POS", "ATM", "ONLINE", "MOBILE"]
CHANNEL_WEIGHTS = [0.45, 0.15, 0.25, 0.15]
TX_TYPES = ["PURCHASE", "WITHDRAWAL", "TRANSFER", "DEPOSIT"]
TX_TYPE_WEIGHTS = [0.65, 0.15, 0.15, 0.05]

PRODUCT_CATALOG = {
    "CARD": ["Дебетовая карта", "Кредитная карта", "Зарплатная карта", "Карта рассрочки"],
    "DEPOSIT": ["Срочный вклад", "Накопительный вклад", "Вклад до востребования"],
    "LOAN": ["Потребительский кредит", "Кредит на авто", "Кредитная линия"],
    "MORTGAGE": ["Ипотека на новостройку", "Ипотека на вторичное жилье"],
    "INVESTMENT": ["Брокерский счет", "ПИФ", "Облигации банка"],
}
PRODUCT_STATUS = ["ACTIVE", "CLOSED", "BLOCKED"]
PRODUCT_STATUS_WEIGHTS = [0.75, 0.20, 0.05]

# clientbase: ровно 6 символов из латинских букв и цифр.
# Порядковый номер клиента переводится в уникальный код через аффинную
# перестановку по модулю 36^6 (множитель взаимно прост с 36^6), поэтому коды
# не повторяются, выглядят случайными и не требуют хранения в памяти.
CLIENTBASE_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
CLIENTBASE_LEN = 6
CLIENTBASE_SPACE = len(CLIENTBASE_ALPHABET) ** CLIENTBASE_LEN
CLIENTBASE_MULT = 1_000_003
CLIENTBASE_SHIFT = 123_456_789


def make_clientbase(n: int) -> str:
    x = (int(n) * CLIENTBASE_MULT + CLIENTBASE_SHIFT) % CLIENTBASE_SPACE
    base = len(CLIENTBASE_ALPHABET)
    chars = []
    for _ in range(CLIENTBASE_LEN):
        x, rem = divmod(x, base)
        chars.append(CLIENTBASE_ALPHABET[rem])
    return "".join(reversed(chars))


def gen_sociodem_batch(clientbases: list):
    rows = []
    today = date.today()
    for cb in clientbases:
        gender = random.choice(["M", "F"])
        age = int(np.clip(np.random.normal(42, 14), 18, 85))
        birth_date = today - timedelta(days=age * 365 + random.randint(0, 364))
        region = random.choice(REGIONS)
        city = random.choice(CITIES_BY_REGION[region])
        education = random.choice(EDUCATION)
        marital = random.choice(MARITAL)
        employment = random.choice(EMPLOYMENT)
        income_segment = random.choices(INCOME_SEGMENTS, weights=INCOME_SEGMENT_WEIGHTS)[0]
        base_income = {"LOW": 700, "MEDIUM": 1500, "HIGH": 3500, "PREMIUM": 8000}[income_segment]
        monthly_income = round(max(300, np.random.normal(base_income, base_income * 0.25)), 2)
        rows.append((
            cb, gender, birth_date.isoformat(), age, region, city,
            education, marital, employment, income_segment, monthly_income,
        ))
    return rows


def gen_transactions_for_client(cb: str, tx_id_start: int, n_tx: int):
    rows = []
    today = datetime.now()
    for i in range(n_tx):
        tx_date = today - timedelta(
            days=random.randint(0, 365), hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
        )
        tx_type = random.choices(TX_TYPES, weights=TX_TYPE_WEIGHTS)[0]
        mcc, category = random.choice(MCC_CATEGORIES)
        currency = random.choices(CURRENCIES, weights=CURRENCY_WEIGHTS)[0]
        if tx_type in ("WITHDRAWAL", "TRANSFER"):
            amount = -round(abs(np.random.lognormal(4.0, 1.0)), 2)
        elif tx_type == "DEPOSIT":
            amount = round(abs(np.random.lognormal(5.5, 1.2)), 2)
        else:
            amount = -round(abs(np.random.lognormal(3.5, 1.0)), 2)
        channel = random.choices(CHANNELS, weights=CHANNEL_WEIGHTS)[0]
        rows.append((
            tx_id_start + i, cb, tx_date.isoformat(sep=" "), amount,
            currency, mcc, category, channel, tx_type,
        ))
    return rows


def gen_products_for_client(cb: str, product_id_start: int, n_products: int):
    rows = []
    today = date.today()
    chosen_types = random.sample(list(PRODUCT_CATALOG.keys()),
                                  k=min(n_products, len(PRODUCT_CATALOG)))
    for i, ptype in enumerate(chosen_types):
        name = random.choice(PRODUCT_CATALOG[ptype])
        open_date = today - timedelta(days=random.randint(30, 365 * 8))
        status = random.choices(PRODUCT_STATUS, weights=PRODUCT_STATUS_WEIGHTS)[0]
        close_date = None
        if status == "CLOSED":
            close_date = (open_date + timedelta(days=random.randint(30, 365 * 3))).isoformat()
        balance = round(abs(np.random.lognormal(6.5, 1.3)), 2) if status != "CLOSED" else 0.0
        rows.append((
            product_id_start + i, cb, ptype, name, open_date.isoformat(),
            close_date, status, balance,
        ))
    return rows


def copy_rows(cur, table, columns, rows):
    buf = io.StringIO()
    for row in rows:
        line = "\t".join(
            r"\N" if v is None else str(v).replace("\t", " ").replace("\n", " ")
            for v in row
        )
        buf.write(line + "\n")
    buf.seek(0)
    cur.copy_expert(
        f"COPY {table} ({', '.join(columns)}) FROM STDIN WITH (FORMAT text, NULL '\\N')",
        buf,
    )


def main():
    parser = argparse.ArgumentParser(description="Генерация тестовых данных клиентов банка")
    parser.add_argument("--n-clients", type=int, default=100, help="Количество клиентов")
    parser.add_argument("--batch-size", type=int, default=10000, help="Размер батча клиентов на одну COPY-операцию")
    parser.add_argument("--min-tx", type=int, default=1, help="Мин. число транзакций на клиента")
    parser.add_argument("--max-tx", type=int, default=30, help="Макс. число транзакций на клиента")
    parser.add_argument("--min-products", type=int, default=0, help="Мин. число продуктов на клиента")
    parser.add_argument("--max-products", type=int, default=4, help="Макс. число продуктов на клиента")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", default=5432, type=int)
    parser.add_argument("--dbname", default="clients_db")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--password", default="admin_pass_change_me")
    parser.add_argument("--truncate", action="store_true", help="Очистить таблицы перед загрузкой")
    args = parser.parse_args()

    conn = psycopg2.connect(
        host=args.host, port=args.port, dbname=args.dbname,
        user=args.user, password=args.password,
    )
    conn.autocommit = False
    cur = conn.cursor()

    if args.truncate:
        cur.execute("TRUNCATE client_transactions, client_products, client_sociodem RESTART IDENTITY;")
        conn.commit()

    tx_id_counter = 1
    product_id_counter = 1
    start_time = time.time()

    for batch_start in range(0, args.n_clients, args.batch_size):
        batch_end = min(batch_start + args.batch_size, args.n_clients)
        clientbases = [make_clientbase(n) for n in range(batch_start, batch_end)]

        sociodem_rows = gen_sociodem_batch(clientbases)
        copy_rows(cur, "client_sociodem", [
            "clientbase", "gender", "birth_date", "age", "region", "city",
            "education", "marital_status", "employment_status",
            "income_segment", "monthly_income",
        ], sociodem_rows)

        tx_rows_all = []
        product_rows_all = []
        for cb in clientbases:
            n_tx = random.randint(args.min_tx, args.max_tx)
            tx_rows = gen_transactions_for_client(cb, tx_id_counter, n_tx)
            tx_id_counter += n_tx
            tx_rows_all.extend(tx_rows)

            n_products = random.randint(args.min_products, args.max_products)
            product_rows = gen_products_for_client(cb, product_id_counter, n_products)
            product_id_counter += len(product_rows)
            product_rows_all.extend(product_rows)

        if tx_rows_all:
            copy_rows(cur, "client_transactions", [
                "transaction_id", "clientbase", "transaction_date", "amount",
                "currency", "mcc_code", "merchant_category", "channel", "transaction_type",
            ], tx_rows_all)

        if product_rows_all:
            copy_rows(cur, "client_products", [
                "product_id", "clientbase", "product_type", "product_name",
                "open_date", "close_date", "status", "balance",
            ], product_rows_all)

        conn.commit()
        elapsed = time.time() - start_time
        print(f"Загружено клиентов: {batch_end}/{args.n_clients} "
              f"(транзакций всего: {tx_id_counter - 1}, продуктов всего: {product_id_counter - 1}) "
              f"[{elapsed:.1f} сек]", file=sys.stderr)

    cur.close()
    conn.close()
    print(f"Готово. Всего времени: {time.time() - start_time:.1f} сек.", file=sys.stderr)


if __name__ == "__main__":
    main()
