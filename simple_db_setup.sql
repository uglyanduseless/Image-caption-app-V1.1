-- 连接到你的RDS数据库后运行这些SQL语句
-- 可以使用MySQL Workbench、命令行或AWS Console

-- 确保使用正确的数据库
USE image_caption_db;

-- 创建主要的images表
CREATE TABLE IF NOT EXISTS images (
    id INT AUTO_INCREMENT PRIMARY KEY,
    filename VARCHAR(255) UNIQUE NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    file_size BIGINT NOT NULL DEFAULT 0,
    mime_type VARCHAR(100),
    s3_key VARCHAR(500) NOT NULL,
    s3_bucket VARCHAR(100) NOT NULL,
    
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
    INDEX idx_thumbnail_status (thumbnail_status)
);

-- 如果你的原始captions表存在，迁移数据
-- 首先检查captions表是否存在
SELECT COUNT(*) as table_exists 
FROM information_schema.tables 
WHERE table_schema = 'image_annotation_app' 
AND table_name = 'captions';

-- 如果captions表存在，运行以下迁移语句：
INSERT IGNORE INTO images (
    filename, 
    original_filename, 
    s3_key, 
    s3_bucket,
    annotation, 
    uploaded_at,
    annotation_status
)
SELECT 
    image_key as filename,
    image_key as original_filename,
    image_key as s3_key,
    'YOUR_BUCKET_NAME' as s3_bucket,  -- 替换为你的实际桶名
    caption as annotation,
    uploaded_at,
    'completed' as annotation_status
FROM captions;

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
    INDEX idx_status (status)
);

-- 验证表创建
SHOW TABLES;
DESCRIBE images;

-- 显示数据迁移结果（如果有的话）
SELECT 
    COUNT(*) as total_images,
    COUNT(CASE WHEN annotation IS NOT NULL THEN 1 END) as images_with_annotations
FROM images;

SELECT 'Database setup completed successfully!' as status;