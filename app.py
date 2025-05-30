import boto3
import mysql.connector
from flask import Flask, request, render_template, jsonify
from werkzeug.utils import secure_filename
import base64
from io import BytesIO
import uuid
import os
from PIL import Image

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this-in-production'

S3_BUCKET = "chqu0370-assignment2-bucket"
S3_REGION = "us-east-1"

DB_HOST = "assignment2-database.cfvojcdvmjtw.us-east-1.rds.amazonaws.com"
DB_NAME = "image_caption_db"
DB_USER = "admin"
DB_PASSWORD = "Qc20000215!"

def get_s3_client():
    return boto3.client("s3", region_name=S3_REGION)

def get_db_connection():
    try:
        connection = mysql.connector.connect(
            host=DB_HOST, database=DB_NAME,
            user=DB_USER, password=DB_PASSWORD,
            autocommit=True
        )
        return connection
    except mysql.connector.Error as err:
        print("Database connection error:", err)
        return None

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "bmp", "webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def get_image_info(file_data):
    try:
        image = Image.open(BytesIO(file_data))
        return {
            'width': image.width,
            'height': image.height,
            'format': image.format,
            'mode': image.mode
        }
    except:
        return {'width': 0, 'height': 0, 'format': 'UNKNOWN', 'mode': 'UNKNOWN'}

@app.route("/")
def upload_form():
    return render_template("index.html")

@app.route("/upload", methods=["GET", "POST"])
def upload_image():
    if request.method == "POST":
        if "file" not in request.files:
            return render_template("upload.html", error="No file selected")

        file = request.files["file"]
        if file.filename == "":
            return render_template("upload.html", error="No file selected")

        if not allowed_file(file.filename):
            return render_template("upload.html", error="Unsupported file type")

        file_data = file.read()
        file_size = len(file_data)
        if file_size > MAX_FILE_SIZE:
            return render_template("upload.html", error="File too large")

        original_filename = secure_filename(file.filename)
        file_extension = original_filename.rsplit(".", 1)[1].lower()
        unique_filename = f"{uuid.uuid4().hex}.{file_extension}"
        image_info = get_image_info(file_data)

        try:
            s3 = get_s3_client()
            s3.put_object(
                Bucket=S3_BUCKET,
                Key=f"uploads/{unique_filename}",
                Body=file_data,
                ContentType=file.content_type or f"image/{file_extension}",
                Metadata={
                    'original-filename': original_filename,
                    'uploaded-by': 'web-app',
                    'file-size': str(file_size)
                }
            )
        except Exception as e:
            return render_template("upload.html", error=f"S3 upload error: {str(e)}")

        try:
            connection = get_db_connection()
            if connection is None:
                return render_template("upload.html", error="Database connection error")

            cursor = connection.cursor()
            cursor.execute("""
                INSERT INTO images (
                    filename, original_filename, file_size, mime_type,
                    s3_key, s3_bucket, image_width, image_height, image_format,
                    upload_ip, annotation_status, thumbnail_status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                unique_filename, original_filename, file_size,
                file.content_type or f"image/{file_extension}",
                unique_filename, S3_BUCKET,
                image_info['width'], image_info['height'], image_info['format'],
                request.remote_addr, 'pending', 'pending'
            ))
            connection.close()
        except Exception as e:
            return render_template("upload.html", error=f"Database error: {str(e)}")

        # Get preview
        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT LEFT(annotation, 100) AS preview FROM images WHERE filename = %s", (unique_filename,))
            result = cursor.fetchone()
            connection.close()
            preview = result["preview"] if result else "Annotation is being generated..."
        except:
            preview = "Annotation is being generated..."

        file_url = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/uploads/{unique_filename}"
        encoded_image = base64.b64encode(file_data).decode("utf-8")
        return render_template("upload.html",
                               image_data=encoded_image,
                               file_url=file_url,
                               filename=unique_filename,
                               processing_message="Image uploaded!",
                               preview=preview)

    return render_template("upload.html")

@app.route("/gallery")
def gallery():
    try:
        connection = get_db_connection()
        if connection is None:
            return render_template("gallery.html", error="Database connection error")

        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT filename, original_filename,
                   LEFT(annotation, 100) AS preview,
                   annotation_status, uploaded_at
            FROM images ORDER BY uploaded_at DESC
        """)
        results = cursor.fetchall()
        connection.close()

        s3 = get_s3_client()
        images_with_data = []

        for row in results:
            image_url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": S3_BUCKET, "Key": f"uploads/{row['filename']}"},
                ExpiresIn=3600
            )
            thumbnail_url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": S3_BUCKET, "Key": f"thumbnails/{row['filename']}"},
                ExpiresIn=3600
            )

            images_with_data.append({
                "filename": row["filename"],
                "original_filename": row["original_filename"],
                "url": image_url,
                "thumbnail_url": thumbnail_url,
                "annotation": row["preview"] or "Generating preview...",
                "annotation_status": row["annotation_status"],
                "uploaded_at": row["uploaded_at"]
            })

        return render_template("gallery.html", images=images_with_data)

    except Exception as e:
        return render_template("gallery.html", error=f"Database error: {str(e)}")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
