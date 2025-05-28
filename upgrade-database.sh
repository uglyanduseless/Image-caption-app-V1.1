#!/bin/bash

# RDS connection details - 使用你现有的配置
DB_HOST="chqu0370-database.chseak6ymu3x.us-east-1.rds.amazonaws.com"
DB_USER="admin"
DB_PASSWORD="Qc20000215!"

SQL_COMMANDS=$(cat <<EOF
/*
  数据库升级脚本 - 从Assignment 1升级到Assignment 2
  这将保留现有数据并添加新的表结构
*/

USE image_caption_db;

-- 备份原有的captions表
CREATE TABLE captions_backup AS SELECT * FROM captions;

-- 创建新的images表 (Assignment 2需要的结构)
CREATE TABLE IF NOT EXISTS images (
    id INT AUTO_INCREMENT PRIMARY KEY,
    filename VARCHAR(255) UNIQUE NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    file_size BIGINT NOT NULL DEFAULT 0,
    mime_type VARCHAR(100),
    s3_key VARCHAR(500) NOT NULL,
    s3_bucket VARCHAR(100) NOT NULL DEFAULT 'chqu0370-bucket',
    
    -- Upload information
    uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    uploaded_by VARCHAR(100) DEFAULT 'web_user',
    upload_ip VARCHAR(45),
    
    -- Image metadata
    image_width INT,
    image_height INT,
    image_format VARCHAR(20),
    
    -- Annotation information (由Lambda函数填充)
    annotation TEXT,
    annotation_generated_at TIMESTAMP NULL,
    annotation_status ENUM('pending', 'processing', 'completed', 'failed') DEFAULT 'pending',
    annotation_error TEXT,
    
    -- Thumbnail information (由Lambda函数填充)
    thumbnail_generated BOOLEAN DEFAULT FALSE,
    thumbnail_path VARCHAR(500),
    thumbnail_size BIGINT DEFAULT 0,
    thumbnail_generated_at TIMESTAMP NULL,
    thumbnail_status ENUM('pending', 'processing', 'completed', 'failed') DEFAULT 'pending',
    thumbnail_error TEXT,
    
    -- Indexes for performance
    INDEX idx_filename (filename),
    INDEX idx_uploaded_at (uploaded_at),
    INDEX idx_annotation_status (annotation_status),
    INDEX idx_thumbnail_status (thumbnail_status),
    INDEX idx_s3_key (s3_key)
);

-- 迁移现有数据从captions表到images表
INSERT INTO images (
    filename, 
    original_filename, 
    s3_key, 
    annotation, 
    uploaded_at,
    annotation_status
)
SELECT 
    image_key as filename,
    image_key as original_filename,
    image_key as s3_key,
    caption as annotation,
    uploaded_at,
    'completed' as annotation_status
FROM captions
ON DUPLICATE KEY UPDATE
    annotation = VALUES(annotation),
    annotation_status = VALUES(annotation_status);

-- 创建处理日志表
CREATE TABLE IF NOT EXISTS processing_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    image_id INT,
    process_type ENUM('annotation', 'thumbnail') NOT NULL,
    status ENUM('started', 'completed', 'failed') NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    error_message TEXT,
    processing_time_ms INT,
    lambda_request_id VARCHAR(100),
    
    FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE,
    INDEX idx_image_process (image_id, process_type),
    INDEX idx_status (status),
    INDEX idx_started_at (started_at)
);

-- 创建应用指标表
CREATE TABLE IF NOT EXISTS app_metrics (
    id INT AUTO_INCREMENT PRIMARY KEY,
    metric_name VARCHAR(100) NOT NULL,
    metric_value DECIMAL(15,4) NOT NULL,
    metric_unit VARCHAR(50),
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_metric_name (metric_name),
    INDEX idx_recorded_at (recorded_at)
);

-- 插入初始指标
INSERT INTO app_metrics (metric_name, metric_value, metric_unit) VALUES
('total_images_uploaded', (SELECT COUNT(*) FROM images), 'count'),
('total_annotations_generated', (SELECT COUNT(*) FROM images WHERE annotation IS NOT NULL), 'count'),
('total_thumbnails_generated', 0, 'count'),
('average_processing_time', 0, 'milliseconds')
ON DUPLICATE KEY UPDATE
    metric_value = VALUES(metric_value);

-- 创建视图方便查询
CREATE OR REPLACE VIEW image_summary AS
SELECT 
    i.id,
    i.filename,
    i.original_filename,
    i.file_size,
    i.uploaded_at,
    i.annotation,
    i.annotation_status,
    i.thumbnail_generated,
    i.thumbnail_path,
    i.thumbnail_status,
    CASE 
        WHEN i.annotation_status = 'completed' AND i.thumbnail_status = 'completed' THEN 'ready'
        WHEN i.annotation_status = 'failed' OR i.thumbnail_status = 'failed' THEN 'error'
        ELSE 'processing'
    END as overall_status
FROM images i;

-- 创建Lambda用户 (如果不存在)
CREATE USER IF NOT EXISTS 'lambda_user'@'%' IDENTIFIED BY 'lambda_password_2024';
GRANT SELECT, INSERT, UPDATE ON image_caption_db.* TO 'lambda_user'@'%';

-- 给现有的admin用户完整权限
GRANT ALL PRIVILEGES ON image_caption_db.* TO 'admin'@'%';

FLUSH PRIVILEGES;

-- 显示迁移结果
SELECT 'Migration completed successfully!' as status;
SELECT COUNT(*) as total_images_migrated FROM images;
SELECT COUNT(*) as original_captions FROM captions_backup;

EOF
)

echo "正在升级数据库架构..."
mysql -h $DB_HOST -u $DB_USER -p$DB_PASSWORD -e "$SQL_COMMANDS"

if [ $? -eq 0 ]; then
    echo "✅ 数据库升级成功!"
    echo "📊 现有数据已迁移到新的表结构"
    echo "🔧 Lambda函数现在可以使用新的数据库架构"
else
    echo "❌ 数据库升级失败，请检查连接信息"
    exit 1
fi