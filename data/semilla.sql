-- Datos ficticios de Colibrí (el mismo e-commerce de las pre-entregas 3 y 4).
-- base_datos.py arma data/colibri.db a partir de este archivo la primera vez que se usa.

CREATE TABLE clientes (
    id      INTEGER PRIMARY KEY,
    nombre  TEXT NOT NULL,
    ciudad  TEXT NOT NULL,
    email   TEXT NOT NULL
);

CREATE TABLE pedidos (
    id          INTEGER PRIMARY KEY,
    cliente_id  INTEGER NOT NULL REFERENCES clientes(id),
    fecha       TEXT NOT NULL,     -- ISO 8601 (aaaa-mm-dd)
    total       INTEGER NOT NULL,  -- en pesos
    estado      TEXT NOT NULL CHECK (estado IN ('preparando', 'en_camino', 'entregado', 'cancelado'))
);

CREATE TABLE envios (
    pedido_id         INTEGER PRIMARY KEY REFERENCES pedidos(id),
    empresa           TEXT NOT NULL,
    codigo            TEXT NOT NULL,
    estado            TEXT NOT NULL,
    ultima_novedad    TEXT NOT NULL,
    entrega_estimada  TEXT
);

INSERT INTO clientes VALUES
    (101, 'Martina López',   'Córdoba',      'martina.lopez@correo.com'),
    (102, 'Julián Pereyra',  'Rosario',      'jpereyra@correo.com'),
    (103, 'Lucía Fernández', 'Buenos Aires', 'lucia.fernandez@correo.com'),
    (104, 'Lucía Fernández', 'Mendoza',      'lfernandez.mza@correo.com'),
    (105, 'Tomás Herrera',   'La Plata',     'tomas.herrera@correo.com');

INSERT INTO pedidos VALUES
    (5001, 102, '2026-08-14',  3200, 'entregado'),
    (5003, 101, '2026-09-05', 12990, 'entregado'),
    (5004, 103, '2026-09-12',  8700, 'entregado'),
    (5007, 102, '2026-09-30',  4800, 'entregado'),
    (5008, 104, '2026-10-02', 15400, 'entregado'),
    (5010, 101, '2026-10-20',  2350, 'cancelado'),
    (5012, 102, '2026-10-28',  6500, 'en_camino'),
    (5013, 104, '2026-11-02', 21300, 'preparando');

INSERT INTO envios VALUES
    (5001, 'Andreani',        'AND-88412093',  'entregado', 'Entregado al titular',                       NULL),
    (5003, 'Andreani',        'AND-88530711',  'entregado', 'Entregado en portería',                      NULL),
    (5004, 'OCA',             'OCA-3301925',   'entregado', 'Entregado al titular',                       NULL),
    (5007, 'OCA',             'OCA-3318840',   'entregado', 'Entregado al titular',                       NULL),
    (5008, 'Andreani',        'AND-88702256',  'entregado', 'Entregado al titular',                       NULL),
    (5012, 'Correo Argentino','CA-000417762AR','en_camino', 'En centro de distribución Rosario (05/11)',  '2026-11-08');
