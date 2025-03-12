-- 创建 current_sales 表
CREATE TABLE current_sales (
    today INT DEFAULT 0,
    yesterday INT DEFAULT 354
);

-- 插入初始数据
INSERT INTO current_sales (today, yesterday) VALUES (0, 354);

-- 创建 current_answer 表
CREATE TABLE current_answer (
    today INT DEFAULT 200,
    yesterday INT DEFAULT 3123
);

-- 插入初始数据
INSERT INTO current_answer (today, yesterday) VALUES (200, 3123);
