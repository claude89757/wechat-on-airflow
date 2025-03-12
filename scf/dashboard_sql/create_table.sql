-- 创建数据库
CREATE DATABASE wx_dashboard;

-- 使用数据库
USE wx_dashboard;

-- 创建employee表
CREATE TABLE employee (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 创建product表
CREATE TABLE product (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 创建channel表
CREATE TABLE channel (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 创建sales_record表
CREATE TABLE sales_record (
    id INT AUTO_INCREMENT PRIMARY KEY,
    employee_id INT,
    product_id INT,
    channel_id INT,
    city VARCHAR(255),
    date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (employee_id) REFERENCES employee(id),
    FOREIGN KEY (product_id) REFERENCES product(id),
    FOREIGN KEY (channel_id) REFERENCES channel(id),
    count INT DEFAULT 5
);

-- 创建answer_record表
CREATE TABLE answer_record (
    id INT AUTO_INCREMENT PRIMARY KEY,
    employee_id INT,
    channel_id INT,
    success TINYINT(1) DEFAULT 0, -- 新增 success 字段，1 表示成功，0 表示失败
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (employee_id) REFERENCES employee(id),
    FOREIGN KEY (channel_id) REFERENCES channel(id),
    count INT DEFAULT 10
);

CREATE TABLE age_distribution (
    id INT AUTO_INCREMENT PRIMARY KEY,
    age_range VARCHAR(50) NOT NULL,  -- 年龄段
    count INT DEFAULT 0,             -- 该年龄段的数量
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- 插入20～30岁的人群数据（假设是最多的）
INSERT INTO age_distribution (age_range, count) 
VALUES ('20-30', 1233);  -- 假设20～30岁有1000人

-- 插入30～40岁的人群数据（排第二）
INSERT INTO age_distribution (age_range, count)
VALUES ('30-40', 524);  -- 假设30～40岁有500人

-- 插入40岁以上的人群数据（随便排一些）
INSERT INTO age_distribution (age_range, count)
VALUES ('40+', 206);  -- 假设40岁以上有200人

-- 10～20岁没有数据，所以不插入该范围


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

