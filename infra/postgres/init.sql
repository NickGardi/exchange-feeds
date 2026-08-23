CREATE TABLE IF NOT EXISTS price_bars (
    window_start TIMESTAMPTZ NOT NULL,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL,
    price NUMERIC NOT NULL,
    volume NUMERIC NOT NULL,
    PRIMARY KEY (window_start, symbol, exchange)
);

CREATE INDEX IF NOT EXISTS price_bars_symbol_idx ON price_bars (symbol);
