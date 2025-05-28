#!/bin/bash

# 使用现有IAM角色部署Lambda函数
# 适用于AWS Academy Learner Lab环境

set -e

# 配置变量 - 请根据你的环境修改
AWS_REGION="us-east-1"
S3_BUCKET="chqu0370-imageapp-bucket"  # 替换为你的S3桶名
RDS_ENDPOINT="imageapp-database.cfvojcdvmjtw.us-east-1.rds.amazonaws.com"  # 替换为你的RDS端点
DB_PASSWORD="Qc20000215!"  # 替换为你的数据库密码
GEMINI_API_KEY="AIzaSyAidnaAr1x6of7glD0eD8kW9-W5zS2dxHg"

# 使用现有的Lambda角色
LAMBDA_ROLE_NAME="RoleForLambdaModLabRole"

echo "🚀 开始部署Lambda函数（使用现有角色）..."

# 获取AWS账户ID和角色ARN
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
LAMBDA_ROLE_ARN="arn:aws:iam::$ACCOUNT_ID:role/$LAMBDA_ROLE_NAME"

echo "📋 使用角色: $LAMBDA_ROLE_ARN"

# 第1步：创建注释Lambda函数
echo "📦 准备注释Lambda函数..."

mkdir -p annotation-lambda
cd annotation-lambda

# 创建requirements.txt
cat > requirements.txt << EOF
boto3==1.34.69
requests==2.31.0
PyMySQL==1.1.0
EOF

# 创建Lambda函数代码
cat > lambda_function.py << 'EOF'
import json
import boto3
import base64
import requests
import pymysql
import os
from urllib.parse import unquote_plus
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')

def lambda_handler(event, context):
    """
    处理S3上传事件，生成图像注释
    """
    try:
        logger.info(f"收到事件: {json.dumps(event)}")
        
        for record in event['Records']:
            bucket_name = record['s3']['bucket']['name']
            object_key = unquote_plus(record['s3']['object']['key'])
            
            # 跳过缩略图文件，避免无限循环
            if object_key.startswith('thumbnails/'):
                logger.info(f"跳过缩略图文件: {object_key}")
                continue
                
            # 只处理图像文件
            if not is_image_file(object_key):
                logger.info(f"跳过非图像文件: {object_key}")
                continue
                
            logger.info(f"开始处理图像注释: {object_key}")
            process_image_annotation(bucket_name, object_key)
        
        return {
            'statusCode': 200,
            'body': json.dumps('注释处理成功')
        }
        
    except Exception as e:
        logger.error(f"Lambda函数执行错误: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps(f'错误: {str(e)}')
        }

def is_image_file(filename):
    """检查是否为图像文件"""
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff'}
    return any(filename.lower().endswith(ext) for ext in image_extensions)

def process_image_annotation(bucket_name, object_key):
    """处理单个图像的注释生成"""
    try:
        # 更新状态为处理中
        update_image_status(object_key, 'processing', None, None)
        
        # 从S3下载图像
        logger.info(f"从S3下载图像: {object_key}")
        response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
        image_data = response['Body'].read()
        
        # 生成注释
        logger.info("调用Gemini API生成注释...")
        annotation = generate_gemini_annotation(image_data)
        
        # 更新数据库
        update_image_status(object_key, 'completed', annotation, None)
        
        logger.info(f"成功处理图像: {object_key}")
        
    except Exception as e:
        error_message = str(e)
        logger.error(f"处理图像 {object_key} 时出错: {error_message}")
        update_image_status(object_key, 'failed', None, error_message)

def generate_gemini_annotation(image_data):
    """使用Gemini API生成图像注释"""
    try:
        # 获取API密钥
        api_key = os.environ.get('GEMINI_API_KEY')
        if not api_key:
            raise Exception("Gemini API密钥未设置")
        
        # 转换图像为base64
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        
        # 调用Gemini API
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        
        payload = {
            "contents": [{
                "parts": [
                    {
                        "text": "Analyze this image and provide a detailed description. Focus on the main subjects, objects, activities, setting, and any notable details. Keep the description concise but informative."
                    },
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": image_base64
                        }
                    }
                ]
            }],
            "generationConfig": {
                "temperature": 0.4,
                "topK": 32,
                "topP": 1,
                "maxOutputTokens": 500
            }
        }
        
        headers = {"Content-Type": "application/json"}
        
        logger.info("发送请求到Gemini API...")
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        annotation = result['candidates'][0]['content']['parts'][0]['text']
        
        logger.info(f"成功生成注释: {annotation[:100]}...")
        return annotation
        
    except requests.exceptions.RequestException as e:
        error_msg = f"Gemini API请求失败: {str(e)}"
        logger.error(error_msg)
        return error_msg
    except KeyError as e:
        error_msg = f"API响应格式错误: {str(e)}"
        logger.error(error_msg)
        return error_msg
    except Exception as e:
        error_msg = f"注释生成失败: {str(e)}"
        logger.error(error_msg)
        return error_msg

def get_db_connection():
    """获取数据库连接"""
    try:
        # 从环境变量获取数据库信息
        db_host = os.environ.get('DB_HOST')
        db_user = os.environ.get('DB_USER', 'admin')
        db_password = os.environ.get('DB_PASSWORD')
        db_name = os.environ.get('DB_NAME', 'image_annotation_app')
        
        if not db_host or not db_password:
            raise Exception("数据库连接信息不完整")
        
        connection = pymysql.connect(
            host=db_host,
            user=db_user,
            password=db_password,
            database=db_name,
            port=3306,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True
        )
        
        return connection
        
    except Exception as e:
        logger.error(f"数据库连接错误: {str(e)}")
        raise

def update_image_status(filename, status, annotation, error_message):
    """更新数据库中的图像状态"""
    try:
        connection = get_db_connection()
        
        with connection.cursor() as cursor:
            # 更新images表
            update_query = """
                UPDATE images 
                SET annotation_status = %s,
                    annotation = %s,
                    annotation_error = %s,
                    annotation_generated_at = CASE WHEN %s = 'completed' THEN NOW() ELSE annotation_generated_at END
                WHERE filename = %s OR s3_key = %s
            """
            
            cursor.execute(update_query, (
                status, annotation, error_message, status, filename, filename
            ))
            
            # 如果没有找到记录，插入新记录
            if cursor.rowcount == 0:
                logger.info(f"未找到记录，插入新记录: {filename}")
                insert_query = """
                    INSERT INTO images (
                        filename, original_filename, s3_key, s3_bucket,
                        annotation, annotation_status, annotation_error
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE 
                    annotation = VALUES(annotation),
                    annotation_status = VALUES(annotation_status),
                    annotation_error = VALUES(annotation_error)
                """
                cursor.execute(insert_query, (
                    filename, filename, filename, os.environ.get('S3_BUCKET', 'unknown'),
                    annotation, status, error_message
                ))
            
            logger.info(f"数据库更新成功: {filename} -> {status}")
            
    except Exception as e:
        logger.error(f"数据库更新失败: {str(e)}")
    finally:
        if 'connection' in locals():
            connection.close()
EOF

# 安装依赖
echo "📥 安装Python依赖..."
pip3 install -r requirements.txt -t . --quiet

# 打包
zip -r ../annotation-lambda.zip . -q
echo "✅ 注释Lambda函数打包完成"

cd ..

# 第2步：创建缩略图Lambda函数
echo "📦 准备缩略图Lambda函数..."

mkdir -p thumbnail-lambda
cd thumbnail-lambda

cat > requirements.txt << EOF
boto3==1.34.69
Pillow==10.2.0
PyMySQL==1.1.0
EOF

cat > lambda_function.py << 'EOF'
import json
import boto3
import pymysql
import os
from PIL import Image
import io
from urllib.parse import unquote_plus
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
THUMBNAIL_SIZE = (200, 200)

def lambda_handler(event, context):
    """
    处理S3上传事件，生成缩略图
    """
    try:
        logger.info(f"收到事件: {json.dumps(event)}")
        
        for record in event['Records']:
            bucket_name = record['s3']['bucket']['name']
            object_key = unquote_plus(record['s3']['object']['key'])
            
            # 跳过缩略图文件，避免无限循环
            if object_key.startswith('thumbnails/'):
                logger.info(f"跳过缩略图文件: {object_key}")
                continue
                
            # 只处理图像文件
            if not is_image_file(object_key):
                logger.info(f"跳过非图像文件: {object_key}")
                continue
                
            logger.info(f"开始生成缩略图: {object_key}")
            generate_thumbnail(bucket_name, object_key)
        
        return {
            'statusCode': 200,
            'body': json.dumps('缩略图生成成功')
        }
        
    except Exception as e:
        logger.error(f"Lambda函数执行错误: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps(f'错误: {str(e)}')
        }

def is_image_file(filename):
    """检查是否为图像文件"""
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff'}
    return any(filename.lower().endswith(ext) for ext in image_extensions)

def generate_thumbnail(bucket_name, object_key):
    """生成缩略图"""
    try:
        # 更新状态为处理中
        update_thumbnail_status(object_key, 'processing', None, 0, None)
        
        # 从S3下载原图
        logger.info(f"从S3下载原图: {object_key}")
        response = s3_client.get_object(Bucket=bucket_name, Key=object_key)
        image_data = response['Body'].read()
        
        # 创建缩略图
        original_image = Image.open(io.BytesIO(image_data))
        
        # 转换为RGB（确保JPEG兼容）
        if original_image.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', original_image.size, (255, 255, 255))
            if original_image.mode == 'P':
                original_image = original_image.convert('RGBA')
            background.paste(original_image, mask=original_image.split()[-1] if 'A' in original_image.mode else None)
            original_image = background
        elif original_image.mode != 'RGB':
            original_image = original_image.convert('RGB')
        
        # 创建缩略图（保持宽高比）
        thumbnail = create_thumbnail_image(original_image)
        
        # 保存为字节
        thumbnail_buffer = io.BytesIO()
        thumbnail.save(thumbnail_buffer, format='JPEG', quality=85, optimize=True)
        thumbnail_data = thumbnail_buffer.getvalue()
        
        # 上传缩略图到S3
        thumbnail_key = f"thumbnails/{object_key}"
        logger.info(f"上传缩略图到S3: {thumbnail_key}")
        
        s3_client.put_object(
            Bucket=bucket_name,
            Key=thumbnail_key,
            Body=thumbnail_data,
            ContentType='image/jpeg',
            Metadata={
                'original-key': object_key,
                'generated-by': 'lambda-thumbnail-generator'
            }
        )
        
        # 更新数据库
        update_thumbnail_status(object_key, 'completed', thumbnail_key, len(thumbnail_data), None)
        
        logger.info(f"成功生成缩略图: {object_key}")
        
    except Exception as e:
        error_message = str(e)
        logger.error(f"生成缩略图失败 {object_key}: {error_message}")
        update_thumbnail_status(object_key, 'failed', None, 0, error_message)

def create_thumbnail_image(original_image):
    """创建缩略图，保持宽高比"""
    original_width, original_height = original_image.size
    target_width, target_height = THUMBNAIL_SIZE
    
    # 计算宽高比
    original_ratio = original_width / original_height
    target_ratio = target_width / target_height
    
    if original_ratio > target_ratio:
        # 原图更宽，以宽度为准
        new_width = target_width
        new_height = int(target_width / original_ratio)
    else:
        # 原图更高，以高度为准
        new_height = target_height
        new_width = int(target_height * original_ratio)
    
    # 调整大小
    thumbnail = original_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    # 如果需要，添加白色背景居中
    if new_width != target_width or new_height != target_height:
        final_thumbnail = Image.new('RGB', THUMBNAIL_SIZE, (255, 255, 255))
        x = (target_width - new_width) // 2
        y = (target_height - new_height) // 2
        final_thumbnail.paste(thumbnail, (x, y))
        return final_thumbnail
    else:
        return thumbnail

def get_db_connection():
    """获取数据库连接"""
    try:
        db_host = os.environ.get('DB_HOST')
        db_user = os.environ.get('DB_USER', 'admin')
        db_password = os.environ.get('DB_PASSWORD')
        db_name = os.environ.get('DB_NAME', 'image_annotation_app')
        
        if not db_host or not db_password:
            raise Exception("数据库连接信息不完整")
        
        connection = pymysql.connect(
            host=db_host,
            user=db_user,
            password=db_password,
            database=db_name,
            port=3306,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True
        )
        
        return connection
        
    except Exception as e:
        logger.error(f"数据库连接错误: {str(e)}")
        raise

def update_thumbnail_status(filename, status, thumbnail_path, thumbnail_size, error_message):
    """更新数据库中的缩略图状态"""
    try:
        connection = get_db_connection()
        
        with connection.cursor() as cursor:
            update_query = """
                UPDATE images 
                SET thumbnail_status = %s,
                    thumbnail_generated = %s,
                    thumbnail_path = %s,
                    thumbnail_size = %s,
                    thumbnail_error = %s,
                    thumbnail_generated_at = CASE WHEN %s = 'completed' THEN NOW() ELSE thumbnail_generated_at END
                WHERE filename = %s OR s3_key = %s
            """
            
            cursor.execute(update_query, (
                status,
                status == 'completed',
                thumbnail_path,
                thumbnail_size,
                error_message,
                status,
                filename,
                filename
            ))
            
            logger.info(f"缩略图状态更新成功: {filename} -> {status}")
            
    except Exception as e:
        logger.error(f"数据库更新失败: {str(e)}")
    finally:
        if 'connection' in locals():
            connection.close()
EOF

# 安装依赖
echo "📥 安装Python依赖..."
pip3 install -r requirements.txt -t . --quiet

# 打包
zip -r ../thumbnail-lambda.zip . -q
echo "✅ 缩略图Lambda函数打包完成"

cd ..

# 第3步：创建Lambda函数
echo "🚀 创建Lambda函数..."

# 创建注释Lambda函数
echo "📝 创建注释Lambda函数..."
aws lambda create-function \
    --function-name image-annotation-function \
    --runtime python3.11 \
    --role "$LAMBDA_ROLE_ARN" \
    --handler lambda_function.lambda_handler \
    --zip-file fileb://annotation-lambda.zip \
    --timeout 300 \
    --memory-size 512 \
    --environment Variables="{GEMINI_API_KEY=$GEMINI_API_KEY,DB_HOST=$RDS_ENDPOINT,DB_PASSWORD=$DB_PASSWORD,S3_BUCKET=$S3_BUCKET,DB_USER=admin,DB_NAME=image_annotation_app}" \
    --region $AWS_REGION 2>/dev/null || echo "⚠️  注释Lambda函数可能已存在"

# 创建缩略图Lambda函数
echo "📝 创建缩略图Lambda函数..."
aws lambda create-function \
    --function-name thumbnail-generator-function \
    --runtime python3.11 \
    --role "$LAMBDA_ROLE_ARN" \
    --handler lambda_function.lambda_handler \
    --zip-file fileb://thumbnail-lambda.zip \
    --timeout 120 \
    --memory-size 1024 \
    --environment Variables="{DB_HOST=$RDS_ENDPOINT,DB_PASSWORD=$DB_PASSWORD,S3_BUCKET=$S3_BUCKET,DB_USER=admin,DB_NAME=image_annotation_app}" \
    --region $AWS_REGION 2>/dev/null || echo "⚠️  缩略图Lambda函数可能已存在"

# 第4步：配置S3事件触发器
echo "🔗 配置S3事件触发器..."

# 给S3权限调用Lambda函数
aws lambda add-permission \
    --function-name image-annotation-function \
    --principal s3.amazonaws.com \
    --action lambda:InvokeFunction \
    --statement-id s3-trigger-annotation \
    --source-arn "arn:aws:s3:::$S3_BUCKET" \
    --region $AWS_REGION 2>/dev/null || echo "注释Lambda权限可能已存在"

aws lambda add-permission \
    --function-name thumbnail-generator-function \
    --principal s3.amazonaws.com \
    --action lambda:InvokeFunction \
    --statement-id s3-trigger-thumbnail \
    --source-arn "arn:aws:s3:::$S3_BUCKET" \
    --region $AWS_REGION 2>/dev/null || echo "缩略图Lambda权限可能已存在"

# 清理临时文件
rm -rf annotation-lambda thumbnail-lambda
rm -f annotation-lambda.zip thumbnail-lambda.zip

echo ""
echo "✅ Lambda函数创建完成！"
echo "=============================="
echo "📋 创建的函数："
echo "   - image-annotation-function (图像注释)"
echo "   - thumbnail-generator-function (缩略图生成)"
echo ""
echo "⚠️  重要：还需要配置S3事件通知"
echo "请手动完成以下步骤："
echo "1. 进入S3控制台 → 选择存储桶 → Properties → Event notifications"
echo "2. 创建事件通知，目标为Lambda函数"
echo "3. 为两个Lambda函数分别创建触发器"
echo ""
echo "🧪 测试建议："
echo "1. 上传图片到S3存储桶"
echo "2. 检查CloudWatch日志: /aws/lambda/image-annotation-function"
echo "3. 检查CloudWatch日志: /aws/lambda/thumbnail-generator-function"
echo "4. 验证数据库中的状态更新"