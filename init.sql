-- ==========================================================
-- Схема БД: клиенты банка (соц-дем, транзакции, продукты)
-- Выполняется автоматически при первом старте контейнера
-- (лежит в /docker-entrypoint-initdb.d/init.sql)
-- ==========================================================

-- 1. Таблица соц-дем данных клиентов
CREATE TABLE IF NOT EXISTS client_sociodem (
    clientbase        VARCHAR(6)      PRIMARY KEY
                      CHECK (clientbase ~ '^[A-Za-z0-9]{6}$'),  -- ровно 6 символов: латиница и цифры
    gender            VARCHAR(1)      NOT NULL,          -- 'M' / 'F'
    birth_date        DATE            NOT NULL,
    age               SMALLINT        NOT NULL,
    region            VARCHAR(100)    NOT NULL,
    city              VARCHAR(100)    NOT NULL,
    education         VARCHAR(50)     NOT NULL,
    marital_status    VARCHAR(30)     NOT NULL,
    employment_status VARCHAR(50)     NOT NULL,
    income_segment    VARCHAR(20)     NOT NULL,           -- LOW / MEDIUM / HIGH / PREMIUM
    monthly_income    NUMERIC(12,2)   NOT NULL,
    created_at        TIMESTAMP       NOT NULL DEFAULT now()
);

-- 2. Таблица транзакций клиентов
CREATE TABLE IF NOT EXISTS client_transactions (
    transaction_id    BIGINT PRIMARY KEY,
    clientbase        VARCHAR(6)      NOT NULL REFERENCES client_sociodem(clientbase),
    transaction_date  TIMESTAMP       NOT NULL,
    amount            NUMERIC(14,2)   NOT NULL,
    currency          VARCHAR(3)      NOT NULL DEFAULT 'BYN',
    mcc_code          SMALLINT        NOT NULL,
    merchant_category VARCHAR(50)     NOT NULL,
    channel           VARCHAR(20)     NOT NULL,           -- POS / ATM / ONLINE / MOBILE
    transaction_type  VARCHAR(20)     NOT NULL            -- PURCHASE / WITHDRAWAL / TRANSFER / DEPOSIT
);

CREATE INDEX IF NOT EXISTS idx_transactions_clientbase
    ON client_transactions(clientbase);
CREATE INDEX IF NOT EXISTS idx_transactions_date
    ON client_transactions(transaction_date);

-- 3. Таблица продуктового владения клиентов
CREATE TABLE IF NOT EXISTS client_products (
    product_id        BIGINT PRIMARY KEY,
    clientbase        VARCHAR(6)      NOT NULL REFERENCES client_sociodem(clientbase),
    product_type      VARCHAR(30)     NOT NULL,           -- CARD / DEPOSIT / LOAN / MORTGAGE / INVESTMENT
    product_name      VARCHAR(100)    NOT NULL,
    open_date         DATE            NOT NULL,
    close_date        DATE,
    status            VARCHAR(20)     NOT NULL,           -- ACTIVE / CLOSED / BLOCKED
    balance            NUMERIC(14,2)  NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_products_clientbase
    ON client_products(clientbase);

-- ==========================================================
-- Read-only пользователь
-- ==========================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'readonly_user') THEN
        CREATE ROLE readonly_user WITH LOGIN PASSWORD 'readonly_pass_change_me';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE clients_db TO readonly_user;
GRANT USAGE ON SCHEMA public TO readonly_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_user;

-- Чтобы новые таблицы (например созданные скриптом позже) тоже были доступны на чтение
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO readonly_user;
