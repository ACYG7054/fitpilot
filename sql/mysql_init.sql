CREATE DATABASE IF NOT EXISTS fitpilot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE fitpilot;

CREATE TABLE IF NOT EXISTS ip_location_ranges (
    id INT PRIMARY KEY AUTO_INCREMENT,
    ip_start_num BIGINT NOT NULL,
    ip_end_num BIGINT NOT NULL,
    province VARCHAR(64) NULL,
    city VARCHAR(64) NULL,
    latitude DOUBLE NOT NULL,
    longitude DOUBLE NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_ip_start_num (ip_start_num),
    INDEX idx_ip_end_num (ip_end_num)
);

CREATE TABLE IF NOT EXISTS gyms (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(128) NOT NULL,
    city VARCHAR(64) NOT NULL,
    address VARCHAR(255) NOT NULL,
    latitude DOUBLE NOT NULL,
    longitude DOUBLE NOT NULL,
    business_hours VARCHAR(128) NULL,
    tags JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_city (city),
    INDEX idx_name (name)
);

CREATE TABLE IF NOT EXISTS human_intervention_tickets (
    id INT PRIMARY KEY AUTO_INCREMENT,
    request_id VARCHAR(64) NOT NULL,
    thread_id VARCHAR(64) NOT NULL,
    active_agent VARCHAR(32) NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    reason VARCHAR(255) NOT NULL,
    payload JSON NULL,
    resolution JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_request_id (request_id),
    INDEX idx_thread_id (thread_id)
);

DELETE FROM ip_location_ranges;
DELETE FROM gyms;

INSERT INTO ip_location_ranges (ip_start_num, ip_end_num, province, city, latitude, longitude) VALUES
    (INET_ATON('203.0.113.0'), INET_ATON('203.0.113.255'), '北京市', '北京', 39.9042, 116.4074),
    (INET_ATON('198.51.100.0'), INET_ATON('198.51.100.255'), '上海市', '上海', 31.2304, 121.4737),
    (INET_ATON('192.0.2.0'), INET_ATON('192.0.2.255'), '广东省', '深圳', 22.5431, 114.0579);

INSERT INTO gyms (name, city, address, latitude, longitude, business_hours, tags) VALUES
    ('FitPilot 望京训练馆', '北京', '北京市朝阳区望京街道阜通东大街 6 号', 39.9969, 116.4701, '06:00-23:00', JSON_ARRAY('力量区', '深蹲架', '团课')),
    ('FitPilot 国贸训练馆', '北京', '北京市朝阳区建国门外大街 1 号', 39.9087, 116.4591, '06:30-22:30', JSON_ARRAY('有氧区', '私教', '更衣室')),
    ('FitPilot 徐汇训练馆', '上海', '上海市徐汇区漕溪北路 339 号', 31.1964, 121.4371, '06:00-23:00', JSON_ARRAY('力量区', '动感单车', '桑拿')),
    ('FitPilot 浦东训练馆', '上海', '上海市浦东新区世纪大道 100 号', 31.2335, 121.5219, '06:30-22:30', JSON_ARRAY('自由重量', '拉伸区', '团课')),
    ('FitPilot 南山训练馆', '深圳', '深圳市南山区科苑路 8 号', 22.5406, 113.9365, '06:00-23:30', JSON_ARRAY('力量区', 'Cross Training', '淋浴')),
    ('FitPilot 福田训练馆', '深圳', '深圳市福田区福华三路 88 号', 22.5347, 114.0596, '06:30-22:30', JSON_ARRAY('游泳池', '瑜伽', '普拉提'));
