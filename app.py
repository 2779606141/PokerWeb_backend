import base64
import io
import tempfile
from threading import Thread

from flask import Flask, jsonify, request, send_file, Response, after_this_request
from flask_cors import CORS
import random  # 导入random模块，用于生成随机数
from QtFusion.config import QF_Config
import cv2  # 导入OpenCV库，用于处理图像
from QtFusion.utils import cv_imread, drawRectBox  # 从QtFusion库中导入cv_imread和drawRectBox函数，用于读取图像和绘制矩形框
from QtFusion.path import abs_path
from flask_socketio import send, SocketIO

from YOLOv8v5Model import YOLOv8v5Detector  # 从YOLOv8Model模块中导入YOLOv8Detector类，用于加载YOLOv8模型并进行目标检测
from datasets.PokerCards.label_name import Label_list
import numpy as np
from PIL import Image

app = Flask(__name__)
CORS(app)
app.config['JSON_AS_ASCII'] = False  # 禁止中文转义
QF_Config.set_verbose(False)
socketio = SocketIO(app, cors_allowed_origins="*")

cls_name = Label_list  # 定义类名列表
colors = [[random.randint(0, 255) for _ in range(3)] for _ in range(len(cls_name))]  # 为每个目标类别生成一个随机颜色

model = YOLOv8v5Detector()  # 创建YOLOv8Detector对象
model.load_model(abs_path("weights/best-yolov8n.pt", path_type="current"))  # 加载预训练的YOLOv8模型


def frame_process(image):  # 定义帧处理函数，用于处理每一帧图像
    # image = cv2.resize(image, (850, 500))  # 将图像的大小调整为850x500
    pre_img = model.preprocess(image)  # 对图像进行预处理
    pred, superimposed_img = model.predict(pre_img)  # 使用模型进行预测
    det = pred[0]  # 获取预测结果
    # 如果有检测信息则进入
    if det is not None and len(det):
        det_info = model.postprocess(pred)  # 对预测结果进行后处理
        for info in det_info:  # 遍历检测信息
            name, bbox, conf, cls_id = info['class_name'], info['bbox'], info['score'], info[
                'class_id']  # 获取类别名称、边界框、置信度和类别ID
            label = '%s %.0f%%' % (name, conf * 100)  # 创建标签，包含类别名称和置信度
            # 画出检测到的目标物
            image = drawRectBox(image, bbox, alpha=0.2, addText=label, color=colors[cls_id])  # 在图像上绘制边界框和标签
    return image


@app.route('/')
def hello_world():
    return 'Hello, World!'


@app.route("/detect", methods=["POST"])
def detect():
    # Check if a file is uploaded
    if 'file' not in request.files:
        return jsonify({"error": "No file part"})

    file = request.files['file']

    # Check if the file is empty
    if file.filename == '':
        return jsonify({"error": "No selected file"})

    # Read the uploaded image
    image = cv2.imdecode(np.fromstring(file.read(), np.uint8), cv2.IMREAD_COLOR)

    # Process the image and perform detection
    pre_img = model.preprocess(image)
    pred, superimposed_img = model.predict(pre_img)
    det = pred[0]
    detections = []
    if det is not None and len(det):
        det_info = model.postprocess(pred)
        for info in det_info:
            name, bbox, conf, cls_id = info['class_name'], info['bbox'], info['score'], info['class_id']
            label = '%s %.0f%%' % (name, conf * 100)  # 创建标签，包含类别名称和置信度
            # 画出检测到的目标物
            image = drawRectBox(image, bbox, alpha=0.2, addText=label, color=colors[cls_id])  # 在图像上绘制边界框和标签
            pil_img = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
            img_io = io.BytesIO()
            pil_img.save(img_io, 'JPEG')
            img_io.seek(0)
            detections.append({
                'class_name': name,
                'bbox': bbox,
                'confidence': conf,
                'class_id': cls_id,
                'label': label
            })
    return send_file(img_io, mimetype='image/jpeg')
    # return jsonify(detections=detections)


@app.route('/detectVideo', methods=['POST'])
def detect_video():
    # 检查是否有文件在请求中
    if 'video' not in request.files:
        return 'No file part', 400
    file = request.files['video']
    # 如果用户没有选择文件，浏览器可能会提交一个没有文件名的空部分
    if file.filename == '':
        return 'No selected file', 400
    # 创建临时文件来保存上传的视频和输出视频
    input_temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
    output_temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')
    # output_path = 'output_video.mp4'
    # 保存上传的视频到临时文件
    file.save(input_temp_file.name)
    # 处理视频
    cap = cv2.VideoCapture(input_temp_file.name)
    fps = cap.get(cv2.CAP_PROP_FPS)
    fourcc = cv2.VideoWriter_fourcc('a', 'v', 'c', '1')
    out = cv2.VideoWriter(output_temp_file.name, fourcc, fps, (850, 500), isColor=True)
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        processed_frame = frame_process(frame)
        out.write(processed_frame)

    cap.release()
    out.release()

    # 返回处理后的视频文件
    # output_temp_file.close()  # 必须先关闭，否则在Windows上可能出错
    return send_file(output_temp_file.name, mimetype='video/mp4', as_attachment=True)

@app.route('/detectCam', methods=['POST'])
def detect_cam():
    # 从请求体中获取图像的Base64编码
    data = request.get_json()
    if data is None or 'image' not in data:
        return jsonify({"error": "Invalid request, no image provided"}), 400

    image_data = data['image']
    # 解码Base64图像数据
    header, encoded = image_data.split(",", 1)
    image_decoded = base64.b64decode(encoded)
    image = cv2.imdecode(np.frombuffer(image_decoded, np.uint8), cv2.IMREAD_COLOR)
    image=frame_process(image)

    # 将处理后的图像转换回Base64以发送回客户端
    _, buffer = cv2.imencode('.jpg', image)
    img_base64 = base64.b64encode(buffer).decode('utf-8')

    # 返回处理后的图像数据
    return jsonify({"processedImage": f"data:image/jpeg;base64,{img_base64}"})

@app.route('/detectCam1', methods=['POST'])
def detect_cam1():
    # 从请求体中获取图像的Base64编码
    data = request.get_json()
    if data is None or 'image' not in data:
        return jsonify({"error": "Invalid request, no image provided"}), 400

    image_data = data['image']
    # 解码Base64图像数据
    header, encoded = image_data.split(",", 1)
    image_decoded = base64.b64decode(encoded)
    image = cv2.imdecode(np.frombuffer(image_decoded, np.uint8), cv2.IMREAD_COLOR)
    pre_img = model.preprocess(image)  # 对图像进行预处理
    pred, superimposed_img = model.predict(pre_img)  # 使用模型进行预测
    det = pred[0]  # 获取预测结果
    card = []
    # 如果有检测信息则进入
    if det is not None and len(det):
        det_info = model.postprocess(pred)  # 对预测结果进行后处理
        for info in det_info:  # 遍历检测信息
            name, bbox, conf, cls_id = info['class_name'], info['bbox'], info['score'], info[
                'class_id']  # 获取类别名称、边界框、置信度和类别ID
            if conf > 0.8:
                card.append(name)
    # 返回处理后的图像数据
    return card

@socketio.on('connect')
def handle_connect():
    print('Client connected')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

@socketio.on('image')
def handle_image(message):
    if isinstance(message, bytes):  # 检查消息是否为二进制
        # 将二进制数据转换为图像
        arr = np.frombuffer(message, np.uint8)
        image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        image = frame_process(image)
        _, buffer = cv2.imencode('.jpg', image)
        socketio.emit('processed', buffer.tobytes())

# @socketio.on('image')
# def handle_image(message):
#     if isinstance(message, bytes):
#         Thread(target=process_image, args=(message,)).start()
#
# def process_image(message):
#     arr = np.frombuffer(message, np.uint8)
#     image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
#     image = frame_process(image)
#     _, buffer = cv2.imencode('.jpg', image)
#     socketio.emit('processed', buffer.tobytes())

if __name__ == '__main__':
    app.run(debug=True)