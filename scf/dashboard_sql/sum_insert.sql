-- 插入 6 条 channel_id = 1 的记录
INSERT INTO sales_record (employee_id, product_id, channel_id, city, created_at)
SELECT 
    FLOOR(1 + RAND() * 3) AS employee_id, -- 随机 employee_id (1, 2, 3)
    1 AS product_id, -- product_id = 1
    1 AS channel_id, -- channel_id = 1
    'City' AS city, -- 假设城市为 'City'
    DATE('2025-02-01') + INTERVAL FLOOR(RAND() * 28) DAY AS created_at -- 随机日期
FROM 
    (SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 UNION SELECT 6) AS temp;

-- 插入 2 条 channel_id = 2 的记录
INSERT INTO sales_record (employee_id, product_id, channel_id, city, created_at)
SELECT 
    FLOOR(1 + RAND() * 3) AS employee_id, -- 随机 employee_id (1, 2, 3)
    1 AS product_id, -- product_id = 1
    2 AS channel_id, -- channel_id = 2
    'City' AS city, -- 假设城市为 'City'
    DATE('2025-02-01') + INTERVAL FLOOR(RAND() * 28) DAY AS created_at -- 随机日期
FROM 
    (SELECT 1 UNION SELECT 2) AS temp;

-- 插入 6 条 channel_id = 1 的记录，转化率为 50%
INSERT INTO answer_record (employee_id, channel_id, success, created_at)
SELECT 
    FLOOR(1 + RAND() * 3) AS employee_id, -- 随机 employee_id (1, 2, 3)
    1 AS channel_id, -- channel_id = 1
    CASE WHEN RAND() < 0.5 THEN 1 ELSE 0 END AS success, -- 50% 转化率
    DATE('2025-02-01') + INTERVAL FLOOR(RAND() * 28) DAY AS created_at -- 随机日期
FROM 
    (SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 UNION SELECT 6) AS temp;

-- 插入 30 条 channel_id = 2 的记录，转化率为 50%
INSERT INTO answer_record (employee_id, channel_id, success, created_at)
SELECT 
    FLOOR(1 + RAND() * 3) AS employee_id, -- 随机 employee_id (1, 2, 3)
    2 AS channel_id, -- channel_id = 2
    CASE WHEN RAND() < 0.5 THEN 1 ELSE 0 END AS success, -- 50% 转化率
    DATE('2025-02-01') + INTERVAL FLOOR(RAND() * 28) DAY AS created_at -- 随机日期
FROM 
    (SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 
     UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9 UNION SELECT 10
     UNION SELECT 11 UNION SELECT 12 UNION SELECT 13 UNION SELECT 14 UNION SELECT 15
     UNION SELECT 16 UNION SELECT 17 UNION SELECT 18 UNION SELECT 19 UNION SELECT 20
     UNION SELECT 21 UNION SELECT 22 UNION SELECT 23 UNION SELECT 24 UNION SELECT 25
     UNION SELECT 26 UNION SELECT 27 UNION SELECT 28 UNION SELECT 29 UNION SELECT 30) AS temp;

-- 插入 6 条 channel_id = 1 的记录
INSERT INTO sales_record (employee_id, product_id, channel_id, city, created_at)
SELECT 
    FLOOR(1 + RAND() * 3) AS employee_id, -- 随机 employee_id (1, 2, 3)
    2 AS product_id, -- product_id = 2
    1 AS channel_id, -- channel_id = 1
    'City' AS city, -- 假设城市为 'City'
    DATE('2025-02-01') + INTERVAL FLOOR(RAND() * 28) DAY AS created_at -- 随机日期
FROM 
    (SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 UNION SELECT 6) AS temp;

-- 插入 11 条 channel_id = 2 的记录
INSERT INTO sales_record (employee_id, product_id, channel_id, city, created_at)
SELECT 
    FLOOR(1 + RAND() * 3) AS employee_id, -- 随机 employee_id (1, 2, 3)
    2 AS product_id, -- product_id = 2
    2 AS channel_id, -- channel_id = 2
    'City' AS city, -- 假设城市为 'City'
    DATE('2025-02-01') + INTERVAL FLOOR(RAND() * 28) DAY AS created_at -- 随机日期
FROM 
    (SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 
     UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9 UNION SELECT 10 
     UNION SELECT 11) AS temp;

-- 插入 6 条 channel_id = 1 的记录，转化率为 80%
INSERT INTO answer_record (employee_id, channel_id, success, created_at)
SELECT 
    FLOOR(1 + RAND() * 3) AS employee_id, -- 随机 employee_id (1, 2, 3)
    1 AS channel_id, -- channel_id = 1
    CASE WHEN RAND() < 0.8 THEN 1 ELSE 0 END AS success, -- 80% 转化率
    DATE('2025-02-01') + INTERVAL FLOOR(RAND() * 28) DAY AS created_at -- 随机日期
FROM 
    (SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 UNION SELECT 6) AS temp;

-- 插入 50 条 channel_id = 2 的记录，转化率为 25%
INSERT INTO answer_record (employee_id, channel_id, success, created_at)
SELECT 
    FLOOR(1 + RAND() * 3) AS employee_id, -- 随机 employee_id (1, 2, 3)
    2 AS channel_id, -- channel_id = 2
    CASE WHEN RAND() < 0.25 THEN 1 ELSE 0 END AS success, -- 25% 转化率
    DATE('2025-02-01') + INTERVAL FLOOR(RAND() * 28) DAY AS created_at -- 随机日期
FROM 
    (SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 
     UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9 UNION SELECT 10
     UNION SELECT 11 UNION SELECT 12 UNION SELECT 13 UNION SELECT 14 UNION SELECT 15
     UNION SELECT 16 UNION SELECT 17 UNION SELECT 18 UNION SELECT 19 UNION SELECT 20
     UNION SELECT 21 UNION SELECT 22 UNION SELECT 23 UNION SELECT 24 UNION SELECT 25
     UNION SELECT 26 UNION SELECT 27 UNION SELECT 28 UNION SELECT 29 UNION SELECT 30
     UNION SELECT 31 UNION SELECT 32 UNION SELECT 33 UNION SELECT 34 UNION SELECT 35
     UNION SELECT 36 UNION SELECT 37 UNION SELECT 38 UNION SELECT 39 UNION SELECT 40
     UNION SELECT 41 UNION SELECT 42 UNION SELECT 43 UNION SELECT 44 UNION SELECT 45
     UNION SELECT 46 UNION SELECT 47 UNION SELECT 48 UNION SELECT 49 UNION SELECT 50) AS temp;

-- 插入 8 条 channel_id = 1 的记录
INSERT INTO sales_record (employee_id, product_id, channel_id, city, created_at)
SELECT 
    FLOOR(1 + RAND() * 3) AS employee_id, -- 随机 employee_id (1, 2, 3)
    3 AS product_id, -- product_id = 3
    1 AS channel_id, -- channel_id = 1
    'City' AS city, -- 假设城市为 'City'
    DATE('2025-02-01') + INTERVAL FLOOR(RAND() * 28) DAY AS created_at -- 随机日期
FROM 
    (SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 
     UNION SELECT 6 UNION SELECT 7 UNION SELECT 8) AS temp;

-- 插入 12 条 channel_id = 2 的记录
INSERT INTO sales_record (employee_id, product_id, channel_id, city, created_at)
SELECT 
    FLOOR(1 + RAND() * 3) AS employee_id, -- 随机 employee_id (1, 2, 3)
    3 AS product_id, -- product_id = 3
    2 AS channel_id, -- channel_id = 2
    'City' AS city, -- 假设城市为 'City'
    DATE('2025-02-01') + INTERVAL FLOOR(RAND() * 28) DAY AS created_at -- 随机日期
FROM 
    (SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 
     UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9 UNION SELECT 10 
     UNION SELECT 11 UNION SELECT 12) AS temp;

-- 插入 9 条 channel_id = 1 的记录，转化率为 70%
INSERT INTO answer_record (employee_id, channel_id, success, created_at)
SELECT 
    FLOOR(1 + RAND() * 3) AS employee_id, -- 随机 employee_id (1, 2, 3)
    1 AS channel_id, -- channel_id = 1
    CASE WHEN RAND() < 0.7 THEN 1 ELSE 0 END AS success, -- 70% 转化率
    DATE('2025-02-01') + INTERVAL FLOOR(RAND() * 28) DAY AS created_at -- 随机日期
FROM 
    (SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 
     UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9) AS temp;

-- 插入 80 条 channel_id = 2 的记录，转化率为 55%
INSERT INTO answer_record (employee_id, channel_id, success, created_at)
SELECT 
    FLOOR(1 + RAND() * 3) AS employee_id, -- 随机 employee_id (1, 2, 3)
    2 AS channel_id, -- channel_id = 2
    CASE WHEN RAND() < 0.55 THEN 1 ELSE 0 END AS success, -- 55% 转化率
    DATE('2025-02-01') + INTERVAL FLOOR(RAND() * 28) DAY AS created_at -- 随机日期
FROM 
    (SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5 
     UNION SELECT 6 UNION SELECT 7 UNION SELECT 8 UNION SELECT 9 UNION SELECT 10
     UNION SELECT 11 UNION SELECT 12 UNION SELECT 13 UNION SELECT 14 UNION SELECT 15
     UNION SELECT 16 UNION SELECT 17 UNION SELECT 18 UNION SELECT 19 UNION SELECT 20
     UNION SELECT 21 UNION SELECT 22 UNION SELECT 23 UNION SELECT 24 UNION SELECT 25
     UNION SELECT 26 UNION SELECT 27 UNION SELECT 28 UNION SELECT 29 UNION SELECT 30
     UNION SELECT 31 UNION SELECT 32 UNION SELECT 33 UNION SELECT 34 UNION SELECT 35
     UNION SELECT 36 UNION SELECT 37 UNION SELECT 38 UNION SELECT 39 UNION SELECT 40
     UNION SELECT 41 UNION SELECT 42 UNION SELECT 43 UNION SELECT 44 UNION SELECT 45
     UNION SELECT 46 UNION SELECT 47 UNION SELECT 48 UNION SELECT 49 UNION SELECT 50
     UNION SELECT 51 UNION SELECT 52 UNION SELECT 53 UNION SELECT 54 UNION SELECT 55
     UNION SELECT 56 UNION SELECT 57 UNION SELECT 58 UNION SELECT 59 UNION SELECT 60
     UNION SELECT 61 UNION SELECT 62 UNION SELECT 63 UNION SELECT 64 UNION SELECT 65
     UNION SELECT 66 UNION SELECT 67 UNION SELECT 68 UNION SELECT 69 UNION SELECT 70
     UNION SELECT 71 UNION SELECT 72 UNION SELECT 73 UNION SELECT 74 UNION SELECT 75
     UNION SELECT 76 UNION SELECT 77 UNION SELECT 78 UNION SELECT 79 UNION SELECT 80) AS temp;

-- sales_record：利用 count 归纳数据
INSERT INTO sales_record (employee_id, product_id, channel_id, city, date, count)
SELECT 
    FLOOR(1 + RAND() * 3) AS employee_id, -- 随机 1-3
    1 AS product_id, 
    1 AS channel_id, 
    '广东' AS city, 
    DATE_ADD('2024-03-01', INTERVAL FLOOR(RAND() * 10) DAY) AS date, 
    FLOOR(2 + RAND() * 5) AS count -- 2 到 5 之间随机
FROM (SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5) t;

INSERT INTO sales_record (employee_id, product_id, channel_id, city, date, count)
SELECT 
    FLOOR(1 + RAND() * 3) AS employee_id, 
    1 AS product_id, 
    2 AS channel_id, 
    '广东' AS city, 
    DATE_ADD('2024-03-01', INTERVAL FLOOR(RAND() * 10) DAY) AS date, 
    FLOOR(3 + RAND() * 6) AS count -- 3 到 6 之间随机
FROM (SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5) t;

-- answer_record: 插入成功的数据 (成功 6% / 0.8%)
INSERT INTO answer_record (employee_id, channel_id, success, count)
SELECT 
    FLOOR(1 + RAND() * 3) AS employee_id, 
    1 AS channel_id, 
    1 AS success,
    1 AS count
FROM (SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4 UNION SELECT 5) t; -- 5 条成功数据 (6%)

INSERT INTO answer_record (employee_id, channel_id, success, count)
SELECT 
    FLOOR(1 + RAND() * 3) AS employee_id, 
    2 AS channel_id, 
    1 AS success,
    1 AS count
FROM (SELECT 1 UNION SELECT 2 UNION SELECT 3 UNION SELECT 4) t; -- 4 条成功数据 (0.8%)

-- 归纳未转化数据
INSERT INTO answer_record (employee_id, channel_id, success, count)
SELECT 
    FLOOR(1 + RAND() * 3) AS employee_id, 
    1 AS channel_id, 
    0 AS success,
    65 AS count; -- 70 - 5 = 65 未成功

INSERT INTO answer_record (employee_id, channel_id, success, count)
SELECT 
    FLOOR(1 + RAND() * 3) AS employee_id, 
    2 AS channel_id, 
    0 AS success,
    596 AS count; -- 600 - 4 = 596 未成功
