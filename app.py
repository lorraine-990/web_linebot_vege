import base64
import logging
import os
import sys
import uuid
from logging.handlers import RotatingFileHandler
import requests
import json
import random
import pandas as pd
from dotenv import load_dotenv
from flask import Flask, abort, render_template, request, send_from_directory, jsonify, Response, send_file
from flask_cors import CORS
from collections import defaultdict
import psycopg2
from linebot.exceptions import InvalidSignatureError
from linebot.v3.messaging import ApiClient, Configuration, MessagingApi
from rec_veg.rec_veg import VegetablePredictor
from nutri_rec.nutri_rec import (
    get_top_vegetables_by_nutrient,
    get_vegetables_by_name_or_alias,
)
import io
import boto3
from linebot.v3.messaging.models import (
    CameraAction,
    CameraRollAction,
    FlexBox,
    FlexBubble,
    FlexButton,
    FlexCarousel,
    FlexImage,
    FlexMessage,
    FlexText,
    ImageMessage,
    MessageAction,
    QuickReply,
    QuickReplyItem,
    ReplyMessageRequest,
    TextMessage,
    URIAction,
    PostbackAction,
)
from linebot.v3.webhook import WebhookHandler
from linebot.v3.webhooks.models import (
    ImageMessageContent,
    MessageEvent,
    TextMessageContent,
    PostbackEvent
)


# ============= 初始設定 ===============

# 取得 .env
load_dotenv()

#  Flask 實例化，指定 js folder 與 template 的資料夾位置。
app = Flask(__name__, static_folder="static", template_folder="templates")
CORS(app)

# 定義首頁
@app.route("/")
def index():
    url_5000 = os.getenv("url_5000", "http://localhost:5000")
    return render_template("index.html", url_5000=url_5000)

# SPA 由 JavaScript 根據網址參數顯示對應內容。
@app.route('/search/<veg_id>')
def veg_search(veg_id):
    return send_file('index.html')


# ============= logger ===============
# 設定日誌等級為 INFO，只記錄以上等級的訊息。
# 移除原本 logger 的所有 handler，避免重複輸出。
# 新增一個 StreamHandler，將日誌輸出到 sys.stdout（通常是終端機）。
# 設定日誌格式，包含時間、logger 名稱、等級、訊息。
# handler 加回 logger
app.logger.setLevel(logging.INFO)
for handler in app.logger.handlers:
    app.logger.removeHandler(handler)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
app.logger.addHandler(handler)


# 日誌中啟動追蹤：辨識是否有成功匯入
app.logger.info("Attempting to import rec_veg...")
from rec_veg.rec_veg import rec_veg
app.logger.info("rec_veg imported successfully.")



NUTRIENT_DISPLAY_MAPPING = {
    "calories_kcal": "熱量",
    "water_g": "水",
    "protein_g": "蛋白質",
    "fat_g": "脂肪",
    "carb_g": "碳水化合物",
    "fiber_g": "膳食纖維",
    "sugar_g": "糖",
    "sodium_mg": "鈉",
    "potassium_mg": "鉀",
    "calcium_mg": "鈣",
    "magnesium_mg": "鎂",
    "iron_mg": "鐵",
    "zinc_mg": "鋅",
    "phosphorus_mg": "磷",
    "vitamin_a_iu": "維生素A",
    "vitamin_c_mg": "維生素C",
    "vitamin_e_mg": "維生素E",
    "vitamin_b1_mg": "維生素B1",
    "folic_acid_ug": "葉酸",
}
UNIT_ABBREVIATION_TO_CHINESE = {
    "kcal": "大卡",
    "g": "克",
    "mg": "毫克",
    "iu": "IU",
    "ug": "微克",
}


# ============= 連線資料庫 ===============
def get_db_connection():
    try:
        conn = psycopg2.connect(
            host=os.getenv("DATABASE_HOST"),
            database=os.getenv("DATABASE_NAME"),
            user=os.getenv("DATABASE_USER"),
            password=os.getenv("DATABASE_PASSWORD"),
            port=os.getenv("DATABASE_PORT"),
        )
        app.logger.info(f"Connecting to database at {os.getenv('DATABASE_HOST')}:{os.getenv('DATABASE_PORT')}/{os.getenv('DATABASE_NAME')}")
        return conn
    except Exception as e:
        app.logger.error(f"Database connection failed: {e}")
        return None


# =============== 新增 API 端點獲取所有蔬菜清單 ===============
@app.route('/api/vegetables', methods=['GET'])
def get_vegetables():
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': '無法連接資料庫'}), 500
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, vege_name FROM basic_vege ORDER BY vege_name;")
        rows = cur.fetchall()
        veg_list = []
        
        for veg_id, veg_name in rows:
            # 隨機價格歷史
            base_price = random.randint(20, 40)
            price_history = [max(5, base_price + random.randint(-3, 3)) for _ in range(30)]
            current_price = price_history[-1]
            previous_price = price_history[-2]
            price_change = (
                f"{'+' if current_price - previous_price >= 0 else ''}"
                f"{round((current_price - previous_price) / previous_price * 100, 1)}%"
            )

            veg_list.append({
                'id': veg_id,
                'name': veg_name,
                'description': f"新鮮{veg_name}，營養豐富，是您餐桌上的最佳選擇。",
                'season': random.choice(['春季', '夏季', '秋季', '冬季', '全年']),
                'priceChange': price_change,
                'currentPrice': current_price,
                'image': f"{os.getenv('url_9000')}/veg-data-bucket/images/{veg_name}.jpg",
                'priceHistory': price_history,
                'nutrition': {
                    '熱量': random.randint(15, 50),
                    '纖維': round(random.uniform(1, 5), 1),
                    '維生素C': random.randint(10, 100),
                    '維生素A': random.randint(0, 500),
                    '鐵質': round(random.uniform(0.3, 3), 1),
                    '鈣質': random.randint(10, 150)
                }
            })

        return jsonify(veg_list)

    except Exception as e:
        app.logger.error(f"Error fetching vegetables: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            cur.close()
            conn.close()


@app.route('/api/vegetables/<int:veg_id>', methods=['GET'])
def get_vegetable_detail(veg_id):
    import random
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': '無法連接資料庫'}), 500

    try:
        cur = conn.cursor()
        cur.execute("SELECT id, vege_name FROM basic_vege WHERE id = %s;", (veg_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({'error': '找不到蔬菜'}), 404

        veg_id, veg_name = row
        base_price = random.randint(20, 40)
        price_history = [max(5, base_price + random.randint(-3, 3)) for _ in range(30)]
        current_price = price_history[-1]
        previous_price = price_history[-2]
        price_change = (
            f"{'+' if current_price - previous_price >= 0 else ''}"
            f"{round((current_price - previous_price) / previous_price * 100, 1)}%"
        )

        vegetable = {
            'id': veg_id,
            'name': veg_name,
            'description': f"新鮮{veg_name}，營養豐富，是您餐桌上的最佳選擇。",
            'season': random.choice(['春季', '夏季', '秋季', '冬季', '全年']),
            'priceChange': price_change,
            'currentPrice': current_price,
            'image': f"{os.getenv('url_9000')}/veg-data-bucket/images/{veg_name}.jpg",
            'imageUrl': f"{os.getenv('url_9000')}/veg-data-bucket/images/{veg_name}.jpg",
            'priceHistory': price_history,
            'nutrition': {
                '熱量': random.randint(15, 50),
                '纖維': round(random.uniform(1, 5), 1),
                '維生素C': random.randint(10, 100),
                '維生素A': random.randint(0, 500),
                '鐵質': round(random.uniform(0.3, 3), 1),
                '鈣質': random.randint(10, 150)
            }
        }
        return jsonify(vegetable)

    except Exception as e:
        app.logger.error(f"Error fetching vegetable detail: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            cur.close()
            conn.close()



@app.route('/api/recipes/<int:veg_id>', methods=['GET'])
def get_recipes(veg_id):
    conn = get_db_connection()
    if conn is None:
        return jsonify({'error': '無法連接資料庫'}), 500

    try:
        cur = conn.cursor()
        # 修正：使用 AS 別名讓資料處理更清晰，並確保查詢所有必要欄位
        cur.execute("""
            SELECT
                mr.id AS recipe_id,
                mr.recipe AS recipe_title,
                rs.step_no,
                rs.description
            FROM main_recipe AS mr
            JOIN recipe_steps AS rs ON mr.id = rs.recipe_id
            WHERE mr.vege_id = %s
            ORDER BY mr.id, rs.step_no;
        """, (veg_id,))
        rows = cur.fetchall()

        if not rows:
            return jsonify({'message': '查無此蔬菜的食譜'}), 200 # 200 表示成功但無資料

        # 使用 defaultdict 處理資料，確保資料結構正確
        recipes_map = defaultdict(lambda: {
            'id': None,
            'title': '',
            'steps': []
        })

        for row in rows:
            # 透過 cursor.description 取得欄位名稱，更安全
            recipe_id = row[0]
            if recipes_map[recipe_id]['id'] is None:
                recipes_map[recipe_id]['id'] = row[0]
                recipes_map[recipe_id]['title'] = row[1]
            
            recipes_map[recipe_id]['steps'].append({
                'step_no': row[2],
                'description': row[3]
            })

        # 將步驟合併為一個單一的字串，並新增預設圖片網址
        recipes_list = []
        for recipe_data in recipes_map.values():
            steps_text = '\n'.join([f"步驟{s['step_no']}. {s['description']}" for s in recipe_data['steps']])
            recipes_list.append({
                'id': recipe_data['id'],
                'title': recipe_data['title'],
                'instructions': steps_text,
                'imageUrl': f'https://dummyimage.com/600x400/80c96a/fff&text={recipe_data["title"]}'
            })
            
        return jsonify(recipes_list)

    except Exception as e:
        # 在錯誤發生時，將錯誤寫入日誌，以便追蹤
        app.logger.error(f"Error fetching recipes for veg_id {veg_id}: {e}")
        # 回傳 500 錯誤給前端
        return jsonify({'error': '伺服器內部錯誤'}), 500
    finally:
        if conn:
            conn.close()

def get_recipes_by_vege_id(vege_id):
    """根據 vege_id 查詢食譜及其步驟"""
    conn = get_db_connection()
    if not conn:
        return []
    
    recipes_data = []
    try:
        cur = conn.cursor()
        
        # 1. 查詢 main_recipe 資料表
        cur.execute("SELECT id, recipe FROM main_recipe WHERE vege_id = %s LIMIT 10", (vege_id,))
        main_recipes = cur.fetchall()
        
        # 定義一個預設圖片網址
        default_image_url = "https://i.imgur.com/your-default-image.png"
        
        for recipe_id, recipe_name in main_recipes:
            # 2. 針對每個食譜，查詢 recipe_steps
            cur.execute("SELECT description FROM recipe_steps WHERE recipe_id = %s ORDER BY step_no ASC", (recipe_id,))
            all_steps = cur.fetchall()
            
            steps_list = [step[0] for step in all_steps]
            
            recipe_description = steps_list[0] if steps_list else ""
            
            recipes_data.append({
                "id": recipe_id,
                "name": recipe_name,
                "description": recipe_description,
                "image_url": default_image_url, # 使用預設圖片網址
                "steps": steps_list
            })
            
    except (Exception, psycopg2.DatabaseError) as error:
        app.logger.error(f"Database query failed: {error}")
        return []
    finally:
        if conn:
            cur.close()
            conn.close()
            
    return recipes_data

def create_recipe_flex_carousel(recipes_data):
    """根據食譜資料建立 Flex Carousel"""
    if not recipes_data:
        return None
        
    bubbles = []
    for recipe in recipes_data:
        steps_text = "步驟：\n" + "\n".join(
            [f"{i+1}. {step}" for i, step in enumerate(recipe["steps"])]
        )
        
        bubble_body_contents = [
            FlexText(text=recipe["name"], weight="bold", size="xl", wrap=True),
            FlexText(text=recipe["description"], size="sm", color="#aaaaaa", wrap=True, margin="sm"),
            FlexText(text=steps_text, size="sm", color="#555555", wrap=True, margin="md"),
        ]
        
        web_url = os.getenv("url_5000")
        
        bubble = FlexBubble(
            direction="ltr",
            hero=FlexImage(
                url=recipe["image_url"],
                size="full",
                aspect_ratio="1.5:1",
                aspect_mode="cover",
                action=URIAction(uri=recipe["image_url"], label="查看圖片"),
            ),
            body=FlexBox(layout="vertical", contents=bubble_body_contents),
            footer=FlexBox(
                layout="vertical",
                spacing="sm",
                contents=[
                    FlexButton(
                        style="link",
                        height="sm",
                        action=URIAction(
                            label="前往網站看得更詳細", uri=f"{web_url}/?section=recipe&id={recipe['id']}"
                        ),
                    ),
                ],
            ),
        )
        bubbles.append(bubble)
        
    return FlexMessage(
        alt_text="相關食譜",
        contents=FlexCarousel(contents=bubbles)
    )


def _create_vegetable_flex_message(
    veg_data_list, alt_text_prefix, is_nutrient_search=False
):
    bubbles = []
    for veg_data in veg_data_list:
        aliases_text = (
            "別名：" + ", ".join(veg_data["aliases"])
            if veg_data["aliases"]
            else "無別名"
        )
        all_nutrients_detail = []
        for i, (nutrient_key, nutrient_value) in enumerate(
            veg_data["all_nutrients"].items()
        ):
            if i < 2:
                continue
            if i >= 7:
                break
            display_name = NUTRIENT_DISPLAY_MAPPING.get(nutrient_key, "")
            if not display_name:
                display_name = nutrient_key.split("_")[0].capitalize()

            current_unit_abbreviation = (
                nutrient_key.split("_")[-1] if "_" in nutrient_key else ""
            )
            current_unit = UNIT_ABBREVIATION_TO_CHINESE.get(
                current_unit_abbreviation, ""
            )

            if pd.isna(nutrient_value):
                nutrient_value_display = "N/A"
            else:
                nutrient_value_display = (
                    f"{nutrient_value:.1f}"
                    if isinstance(nutrient_value, (int, float))
                    else str(nutrient_value)
                )
            all_nutrients_detail.append(
                f"{display_name}：{nutrient_value_display}{current_unit}"
            )

        all_nutrients_text = "營養資訊(每100 克可食部分)：\n" + "\n".join(
            all_nutrients_detail
        )
        bubble_body_contents = [
            FlexText(text=veg_data["chinese_name"], weight="bold", size="xl"),
            FlexText(
                text=aliases_text, size="sm", color="#aaaaaa", wrap=True, margin="sm"
            ),
            FlexText(
                text=all_nutrients_text,
                size="sm",
                color="#555555",
                wrap=True,
                margin="md",
            ),
        ]
        if (
            is_nutrient_search
            and "nutrient_name" in veg_data
            and "nutrient_value" in veg_data
            and "unit" in veg_data
        ):
            bubble_body_contents.insert(
                1,
                FlexText(
                    text=f"查詢成分：{veg_data['nutrient_name']} {veg_data['nutrient_value']}{veg_data['unit']}",
                    size="md",
                    margin="md",
                ),
            )

        import urllib.parse
        flex_image_url = os.getenv("url_9000")
        web_url = os.getenv("url_5000")
        veg_name = veg_data["chinese_name"]
        image_filename = urllib.parse.quote(f"{veg_name}.jpg")
        image_url = f"{flex_image_url}/veg-data-bucket/images/{image_filename}"

        bubble = FlexBubble(
    direction="ltr",
    hero=FlexImage(
        url=image_url,
        size="full",
        aspect_ratio="1.5:1",
        aspect_mode="cover",
        action=URIAction(uri=image_url, label="查看圖片"),
    ),
    body=FlexBox(layout="vertical", contents=bubble_body_contents),
    footer=FlexBox(
        layout="vertical",
        spacing="sm",
        contents=[
            # 這裡加入條件判斷，只有當 veg_data 包含 'id' 時才建立按鈕
            FlexButton(
                style="link",
                height="sm",
                action=PostbackAction(
                    label="查看相關食譜",
                    data=f"action=get_recipes&veg_id={veg_data['id']}",
                    display_text="為您查詢相關食譜..."
                ),
            ) if 'id' in veg_data else None,
            FlexButton(
                style="link",
                height="sm",
                action=URIAction(
                    label="前往網站看得更詳細", uri=f"{web_url}/?section=detail&id={veg_data['id']}"
                ),
            ) if 'id' in veg_data else None,
        ],
    ),
)
        bubbles.append(bubble)
    if not bubbles:
        return TextMessage(
            text="沒有找到符合條件的蔬菜。"
        )
    else:
        return FlexMessage(
            alt_text=f"{alt_text_prefix}相關蔬菜",
            contents=FlexCarousel(contents=bubbles),
        )

# ... (其餘程式碼不變)
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    raise ValueError(
        "LINE_CHANNEL_ACCESS_TOKEN or LINE_CHANNEL_SECRET not set in environment variables."
    )
app.logger.info(
    f"LINE_CHANNEL_ACCESS_TOKEN loaded (length: {len(LINE_CHANNEL_ACCESS_TOKEN)})"
)
app.logger.info(f"LINE_CHANNEL_SECRET loaded (length: {len(LINE_CHANNEL_SECRET)})")
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
api_client = ApiClient(configuration)
messaging_api = MessagingApi(api_client)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    app.logger.info("Request signature: " + signature)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("Invalid signature. Request body: " + body)
        abort(400)
    except Exception as e:
        import traceback
        app.logger.error(f"Unhandled exception in callback: {e}")
        app.logger.error(traceback.format_exc())
        abort(500)
    return "OK"

# 新增 PostbackEvent 處理
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    app.logger.info(f"Received postback data: {data}")
    
    # 檢查是否為食譜查詢
    if data.startswith("action=get_recipes"):
        # 解析 veg_id
        try:
            params = dict(param.split('=') for param in data.split('&'))
            veg_id = int(params.get('veg_id'))
        except (ValueError, KeyError):
            messaging_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="食譜查詢參數錯誤。")]
                )
            )
            return

        # 查詢食譜
        recipes = get_recipes_by_vege_id(veg_id)
        
        # 建立回覆訊息
        if recipes:
            flex_message = create_recipe_flex_carousel(recipes)
            messaging_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[flex_message]
                )
            )
        else:
            messaging_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text="找不到相關食譜喔！")]
                )
            )

@handler.add(MessageEvent, message=ImageMessageContent)
def handle_image_message(event):
    app.logger.info("進入 handle_image_message 函數 ")
    image_filename = f"temp_image_{uuid.uuid4()}.jpg"
    try:
        # ... (下載圖片和辨識的程式碼不變)
        headers = {"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"}
        url = f"https://api-data.line.me/v2/bot/message/{event.message.id}/content"
        response = requests.get(url, headers=headers, stream=True)
        if response.status_code != 200:
            raise Exception(f"圖片下載失敗，狀態碼：{response.status_code}")
        with open(image_filename, "wb") as f:
            for chunk in response.iter_content():
                f.write(chunk)
        with open(image_filename, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
        recognition_result = rec_veg(encoded_string)
        veg_name = "未知蔬菜"
        confidence = 0.0
        try:
            lines = recognition_result.split("\n")
            if len(lines) >= 2:
                if "預測類別：" in lines[0]:
                    veg_name = lines[0].replace("預測類別：", "").strip()
                if "信心度：" in lines[1]:
                    confidence_str = (
                        lines[1].replace("信心度：", "").replace("%", "").strip()
                    )
                    confidence = float(confidence_str) / 100.0
        except Exception as e:
            app.logger.error(f"解析 recognition_result 失敗: {e}")
            import traceback
            app.logger.error(traceback.format_exc())
            veg_name = "未知蔬菜"
            confidence = 0.0
        prefix_message_text = ""
        if confidence >= 0.8:
            prefix_message_text = f'哼哼 根據我的判斷 它就是"{veg_name}"!!'
            if confidence == 1.0:
                prefix_message_text = f'真相只有一個 就是"{veg_name}"!!'
        elif confidence >= 0.5:
            prefix_message_text = f'可能是"{veg_name}"   也許讓我再看更清楚的一張'
        else:
            prefix_message_text = "歐內該  請提供更清晰的"
        if confidence >= 0.5:
            prefix_message_text += f"\n我有{confidence*100:.0f}%的信心"

        # 這裡的調用已移除 MinIO 檔案名稱參數
        vegetable_details = get_vegetables_by_name_or_alias(veg_name)
        
        messages_to_reply = [TextMessage(text=prefix_message_text)]
        if (
            confidence >= 0.5
            and vegetable_details
            and not isinstance(vegetable_details, str)
        ):
            flex_message = _create_vegetable_flex_message(
                vegetable_details, f"辨識結果：{veg_name}"
            )
            if flex_message:
                messages_to_reply.append(flex_message)
        elif confidence < 0.5:
            pass
        else:
            messages_to_reply.append(TextMessage(text="未能找到該蔬菜的詳細資訊。"))
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token, messages=messages_to_reply
            )
        )
        app.logger.info("Image recognition reply sent successfully.")
    except Exception as e:
        import traceback
        app.logger.info(traceback.format_exc())
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    TextMessage(text=f"圖片處理失敗：{e}")
                ],
            )
        )
    finally:
        if os.path.exists(image_filename):
            os.remove(image_filename)

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text_message(event):
    print(f"Received text: {event.message.text}")
    try:
        reply_message = None
        text = event.message.text.strip()

        if text == "上傳圖片":
            reply_message = TextMessage(
                text="請選擇拍照或從相簿選擇圖片(請盡量讓背景單純)：",
                quick_reply=QuickReply(
                    items=[
                        QuickReplyItem(action=CameraAction(label="開啟相機")),
                        QuickReplyItem(action=CameraRollAction(label="從相簿選擇")),
                    ]
                ),
            )
        elif text == "輸入營養成分":
            reply_message = TextMessage(
                text="請輸入您想查詢的營養成分，例如：蛋白質、維生素C、鐵質\n您也可以輸入蔬菜名稱或別名，例如：高麗菜、大白菜"
            )
        else:
            nutrient_input = text
            print(f"DEBUG: Processing nutrient input: '{nutrient_input}'")

            # 這裡的調用已移除 MinIO 檔案名稱參數
            recommendation_result = get_top_vegetables_by_nutrient(nutrient_input)
            print(f"DEBUG: Recommendation result for '{nutrient_input}': {recommendation_result}")
            
            if recommendation_result and isinstance(recommendation_result, list):
                valid_vegetables = []
                for veg in recommendation_result:
                    if veg and (veg.get('id') or veg.get('vege_id')) and veg.get('chinese_name') and veg.get('all_nutrients'):
                        temp_veg = veg.copy()
                        if 'vege_id' in temp_veg:
                            temp_veg['id'] = temp_veg['vege_id']
                        valid_vegetables.append(temp_veg)
                
                if valid_vegetables:
                    reply_message = _create_vegetable_flex_message(
                        valid_vegetables,
                        f"為您推薦 {nutrient_input} 含量最高的蔬菜",
                        is_nutrient_search=True,
                    )
                else:
                    print(f"DEBUG: No valid data found for '{nutrient_input}' after filtering.")
            
            if not reply_message:
                # 這裡的調用已移除 MinIO 檔案名稱參數
                vegetable_search_result = get_vegetables_by_name_or_alias(nutrient_input)
                print(f"DEBUG: Vegetable search result for '{nutrient_input}': {vegetable_search_result}")

                if vegetable_search_result and isinstance(vegetable_search_result, list):
                    limited_vegetable_search_result = vegetable_search_result[:12]
                    valid_vegetables = []
                    for veg in limited_vegetable_search_result:
                        if veg and (veg.get('id') or veg.get('vege_id')) and veg.get('chinese_name') and veg.get('all_nutrients'):
                            temp_veg = veg.copy()
                            if 'vege_id' in temp_veg:
                                temp_veg['id'] = temp_veg['vege_id']
                            valid_vegetables.append(temp_veg)

                    if valid_vegetables:
                        reply_message = _create_vegetable_flex_message(
                            valid_vegetables,
                            f"為您推薦 {nutrient_input} 相關蔬菜",
                        )
                    else:
                        print(f"DEBUG: No valid data found for '{nutrient_input}' after filtering.")
            
            if not reply_message:
                reply_message = TextMessage(text="沒有找到符合條件的營養成分或蔬菜。請檢查您的輸入。")

        if reply_message:
            messaging_api.reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[reply_message])
            )
            print("Reply sent successfully.")

    except Exception as e:
        print(f"Failed to reply: {e}")



@app.route("/api/image/<filename>")
def get_image(filename):
    # ... (MinIO 函式不變)
    s3 = boto3.client(
        "s3",
        endpoint_url=os.getenv("MINIO_ENDPOINT"),
        aws_access_key_id=os.getenv("MINIO_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("MINIO_SECRET_KEY"),
        config=boto3.session.Config(signature_version="s3v4"),
    )
    bucket = os.getenv("MINIO_BUCKET_NAME", "veg-data-bucket")
    key = f"images/{filename}"
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return Response(obj["Body"].read(), mimetype="image/jpeg")
    except Exception as e:
        return "Not found", 404

@app.route("/api/csv/<filename>")
def get_csv(filename):
    # ... (MinIO 函式不變)
    s3 = boto3.client(
        "s3",
        endpoint_url=os.getenv("MINIO_ENDPOINT"),
        aws_access_key_id=os.getenv("MINIO_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("MINIO_SECRET_KEY"),
        config=boto3.session.Config(signature_version="s3v4"),
    )
    bucket = os.getenv("MINIO_BUCKET_NAME", "veg-data-bucket")
    key = filename
    app.logger.info(f"嘗試從 MinIO 取得 bucket={bucket} key={key}")
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return Response(obj["Body"].read(), mimetype="text/csv")
    except Exception as e:
        print(f"MinIO 取檔失敗: {e}")
        app.logger.error(f"MinIO 取檔失敗: {e}")
        return "Not found", 404

try:
    predictor = VegetablePredictor(
        model_path="rec_veg/model_mnV2(best).keras", classes_path="rec_veg/classes.csv"
    )
except Exception as e:
    print(f"無法啟動應用程式: {e}")
    predictor = None

@app.route("/predict", methods=["POST"])
def handle_prediction():
    if not predictor:
        return jsonify({"error": "伺服器初始化失敗，模型未載入。"}), 500
    try:
        data = request.get_json()
        if not data or "image" not in data:
            return jsonify({"error": "請求格式錯誤，未包含 'image' 欄位"}), 400
        base64_image = data["image"]
        prediction_result = predictor.predict(base64_image)
        return jsonify(prediction_result)
    except Exception as e:
        print(f"API 處理時發生錯誤: {e}")
        return jsonify({"error": "伺服器內部錯誤，無法辨識圖片"}), 500




if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)