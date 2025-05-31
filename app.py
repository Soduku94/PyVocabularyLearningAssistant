# app.py
import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_dance.contrib.google import make_google_blueprint, google
from flask_sqlalchemy import SQLAlchemy  # <<< THÊM DÒNG NÀY
from sqlalchemy import func
from sqlalchemy.sql import case
from dotenv import load_dotenv # Thêm dòng này
load_dotenv()


from flask_migrate import Migrate
from datetime import datetime  # <<< THÊM DÒNG NÀY
from models import db, User, VocabularyList, VocabularyEntry, APILog
from deep_translator import GoogleTranslator
import requests
from functools import wraps

app = Flask(__name__)

app.config["GOOGLE_OAUTH_CLIENT_ID"] = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
app.config["GOOGLE_OAUTH_CLIENT_SECRET"] = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "a_default_fallback_secret_key_if_not_set_for_dev") # Nên có fallback cho dev

# --- Cấu hình SQLAlchemy ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///vocabulary_app.db'  # <<< THÊM: Đường dẫn tới file database SQLite
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # <<< THÊM: Tắt thông báo không cần thiết

db.init_app(app)
migrate = Migrate(app, db)

# --- Tạo Google Blueprint với Flask-Dance ---
google_bp = make_google_blueprint(
    scope=[
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile"
    ],
)


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        current_user_db_id = session.get("db_user_id")
        if not current_user_db_id:  # Chưa đăng nhập
            flash("Vui lòng đăng nhập để truy cập trang này.", "warning")
            # Bạn có thể chuyển hướng đến trang login modal hoặc trang login riêng
            # Hiện tại, pop-up login được kích hoạt từ nút ở header trên trang chủ
            return redirect(url_for('home', open_login_modal=True))  # Gợi ý: thêm param để JS tự mở modal

        user = User.query.get(current_user_db_id)
        if not user or not user.is_admin:  # Không phải admin hoặc không tìm thấy user
            flash("Bạn không có quyền truy cập vào trang quản trị.", "danger")
            return redirect(url_for('home'))
        return f(*args, **kwargs)

    return decorated_function


def get_current_user_info():
    db_user_id = session.get("db_user_id")
    if db_user_id:
        user_from_db = User.query.get(db_user_id)  # User model đã được import từ models.py
        if user_from_db:
            return {
                "name": user_from_db.name,
                "email": user_from_db.email,
                "picture": user_from_db.picture_url,
                "is_admin": user_from_db.is_admin  # <<< ĐẢM BẢO CÓ DÒNG NÀY
            }
    # Xử lý trường hợp đăng nhập bằng Google mà chưa có db_user_id trong session (lần đầu)
    if google.authorized:  # google object từ Flask-Dance
        user_info_google = session.get("user_info")  # Thông tin tạm từ Google session
        if user_info_google:
            # Trong trường hợp này, chúng ta chưa có thông tin is_admin từ Google trực tiếp
            # Nếu user đã có trong DB (được tạo/cập nhật trong route home), is_admin sẽ có khi get_current_user_info được gọi lại với db_user_id
            # Tạm thời, nếu chỉ có google session, is_admin có thể coi là False cho lần render đầu tiên này
            user_info_google['is_admin'] = False  # Hoặc logic phức tạp hơn để query DB nếu cần ngay
            return user_info_google
    return None


app.register_blueprint(google_bp, url_prefix="/login")


# --- Các Route của ứng dụng ---
@app.route('/')
def home():
    display_user_info = get_current_user_info()  # Lấy thông tin user hiện tại (nếu có)

    # Xử lý sau khi Google xác thực (có thể đã có user_info trong session từ Google)
    if google.authorized and not session.get("db_user_id"):
        # Lấy thông tin từ Google nếu chưa có trong session["user_info"]
        # (Đoạn này có thể đã được Flask-Dance hoặc logic trước đó xử lý và đưa vào session["user_info"])
        user_info_from_google = session.get("user_info")
        if not user_info_from_google:  # Nếu chưa có, thử lấy lại
            try:
                resp = google.get("/oauth2/v2/userinfo")
                if resp.ok:
                    user_info_from_google = resp.json()
                    session["user_info"] = user_info_from_google  # Lưu lại
                else:
                    flash("Không thể lấy thông tin từ Google. Vui lòng thử lại.", "danger")
                    return redirect(url_for('logout'))  # Logout nếu không lấy được info
            except Exception as e:
                print(f"Error fetching user info from Google: {e}")
                flash("Lỗi kết nối tới Google. Vui lòng thử lại.", "danger")
                return redirect(url_for('logout'))

        if user_info_from_google:
            google_id = user_info_from_google.get("id") or user_info_from_google.get("sub")
            email = user_info_from_google.get("email")

            if google_id and email:
                user = User.query.filter_by(google_id=google_id).first()
                if not user:  # Chưa có user với google_id này, thử tìm bằng email
                    user = User.query.filter_by(email=email).first()
                    if user:  # Đã có user với email này (có thể đăng ký form trước đó)
                        if user.is_blocked:
                            flash('Tài khoản của bạn (liên kết với email này) đã bị khóa.', 'danger')
                            return redirect(url_for('logout'))  # Ngăn đăng nhập

                        # Nếu user này chưa có google_id, liên kết nó
                        if not user.google_id:
                            user.google_id = google_id
                            # Cập nhật thêm thông tin từ Google nếu muốn (name, picture)
                            user.name = user.name or user_info_from_google.get("name")
                            user.picture_url = user.picture_url or user_info_from_google.get("picture")
                            try:
                                db.session.commit()
                            except Exception as e:
                                db.session.rollback()
                                flash("Lỗi khi liên kết tài khoản Google.", "danger")
                                return redirect(url_for('logout'))

                        # Nếu user này (tìm thấy qua email) chưa có mật khẩu VÀ đã liên kết google_id
                        # Hoặc user này đã có google_id nhưng chưa có password_hash
                        if not user.password_hash:
                            # Lưu thông tin cần thiết từ Google vào session để dùng ở trang hoàn tất
                            session['google_auth_pending_setup'] = {
                                'google_id': google_id,
                                'email': email,
                                'name': user_info_from_google.get("name"),
                                'picture': user_info_from_google.get("picture")
                            }
                            return redirect(url_for('google_complete_setup_page'))
                        else:  # User đã có google_id và cả password_hash (đã hoàn tất setup)
                            session['db_user_id'] = user.id
                            display_user_info = get_current_user_info()  # Cập nhật display_user_info

                    else:  # User hoàn toàn mới (không có google_id, không có email)
                        # Lưu thông tin cần thiết từ Google vào session
                        session['google_auth_pending_setup'] = {
                            'google_id': google_id,
                            'email': email,
                            'name': user_info_from_google.get("name"),
                            'picture': user_info_from_google.get("picture")
                        }
                        return redirect(url_for('google_complete_setup_page'))

                else:  # Đã tìm thấy user với google_id
                    if user.is_blocked:
                        flash('Tài khoản của bạn đã bị khóa.', 'danger')
                        return redirect(url_for('logout'))

                    if not user.password_hash:  # Đã có google_id nhưng chưa đặt mật khẩu hệ thống
                        session['google_auth_pending_setup'] = {  # Đảm bảo thông tin mới nhất từ Google
                            'google_id': user.google_id,  # Nên lấy từ DB để nhất quán nếu đã có
                            'email': user.email,
                            'name': user_info_from_google.get("name", user.name),
                            'picture': user_info_from_google.get("picture", user.picture_url)
                        }
                        return redirect(url_for('google_complete_setup_page'))
                    else:  # User đã có google_id và password_hash -> đăng nhập thành công
                        session['db_user_id'] = user.id
                        display_user_info = get_current_user_info()  # Cập nhật display_user_info
            else:  # Không lấy được google_id hoặc email từ Google
                flash("Không thể xác thực với Google, thiếu thông tin định danh.", "danger")
                return redirect(url_for('logout'))

    # Hiển thị trang chủ
    return render_template('index.html', user_info=display_user_info)


@app.route('/auth/google/complete-setup', methods=['GET', 'POST'])
def google_complete_setup_page():
    # Kiểm tra xem có thông tin người dùng Google đang chờ xử lý trong session không
    pending_google_user = session.get('google_auth_pending_setup')
    if not pending_google_user:
        flash("Không có thông tin để hoàn tất đăng ký Google, hoặc phiên đã hết hạn.", "warning")
        return redirect(url_for('home'))

    # Lấy thông tin admin hiện tại (cho base.html, nếu trang này kế thừa base.html)
    # Nếu trang này là một trang riêng biệt không có sidebar/header như base.html, bạn có thể không cần user_info này.
    # Tuy nhiên, để nhất quán và nếu có flash message, kế thừa base.html vẫn tốt.
    current_display_user_info = get_current_user_info()

    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        agree_terms = request.form.get('agree_terms') == 'on'  # Checkbox trả về 'on' nếu được chọn

        if not password or not confirm_password:
            flash("Vui lòng nhập mật khẩu và xác nhận mật khẩu.", "danger")
        elif len(password) < 6:
            flash("Mật khẩu phải có ít nhất 6 ký tự.", "danger")
        elif password != confirm_password:
            flash("Mật khẩu và xác nhận mật khẩu không khớp.", "danger")
        elif not agree_terms:
            flash("Bạn phải đồng ý với các điều khoản và điều kiện để tiếp tục.", "danger")
        else:
            # Tất cả thông tin hợp lệ, tiến hành tạo/cập nhật user
            google_id = pending_google_user['google_id']
            email = pending_google_user['email']
            name = pending_google_user.get('name')
            picture = pending_google_user.get('picture')

            user = User.query.filter_by(google_id=google_id).first()
            if not user:  # Nếu chưa có user với google_id này, thử lại bằng email
                user = User.query.filter_by(email=email).first()

            try:
                if user:  # User đã tồn tại (ví dụ qua email, giờ liên kết google_id và set password)
                    user.google_id = google_id  # Đảm bảo google_id được gán
                    user.set_password(password)
                    user.name = user.name or name  # Cập nhật name nếu user.name chưa có
                    user.picture_url = user.picture_url or picture  # Cập nhật picture nếu user.picture_url chưa có
                else:  # User hoàn toàn mới
                    user = User(
                        google_id=google_id,
                        email=email,
                        name=name,
                        picture_url=picture,
                        is_admin=False,  # Mặc định
                        is_blocked=False  # Mặc định
                    )
                    user.set_password(password)
                    db.session.add(user)

                db.session.commit()

                # Đăng nhập người dùng
                session.pop('google_auth_pending_setup', None)  # Xóa thông tin tạm khỏi session
                session['db_user_id'] = user.id
                session['user_info'] = {  # Tạo user_info cho session từ DB
                    'name': user.name,
                    'email': user.email,
                    'picture': user.picture_url,
                    'is_admin': user.is_admin
                }
                flash('Hoàn tất đăng ký và đăng nhập thành công!', 'success')
                return redirect(url_for('home'))
            except Exception as e:
                db.session.rollback()
                flash(f"Có lỗi xảy ra khi lưu thông tin: {str(e)}", "danger")
                print(f"Lỗi khi hoàn tất đăng ký Google cho {email}: {e}")

    # Cho GET request, hoặc nếu POST có lỗi thì render lại form
    return render_template('auth/google_complete_setup.html',
                           user_info=current_display_user_info,  # Cho base.html
                           google_user_name=pending_google_user.get('name', 'User'),
                           google_user_email=pending_google_user.get('email'))


@app.route('/login-with-google')
def login_with_google():
    if not google.authorized:
        return redirect(url_for("google.login"))
    return redirect(url_for("home"))


@app.route('/logout')
def logout():
    token_key = f"{google_bp.name}_oauth_token"
    if token_key in session:
        del session[token_key]
    if "user_info" in session:
        del session["user_info"]
    if "db_user_id" in session:  # Xóa cả db_user_id
        del session["db_user_id"]
    return redirect(url_for("home"))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get("db_user_id") or google.authorized:
        # Nếu dùng AJAX, client sẽ không thấy redirect này trừ khi response là redirect.
        # Nếu là GET request đến /login khi đã đăng nhập, thì redirect về home.
        if request.method == 'GET':
            return redirect(url_for('home'))
        # Nếu là POST (tức là AJAX submit) mà đã đăng nhập, thì không nên xảy ra, nhưng trả về lỗi
        return jsonify({"success": False, "message": "Bạn đã đăng nhập rồi."}), 400

    if request.method == 'POST':
        data = request.get_json()  # Nhận dữ liệu JSON từ AJAX
        email = data.get('email')
        password = data.get('password')

        if not email or not password:
            return jsonify({"success": False, "message": "Vui lòng nhập email và mật khẩu."}), 400

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            if user.is_blocked:
                return jsonify({"success": False,
                                "message": "Tài khoản của bạn đã bị khóa. Vui lòng liên hệ quản trị viên."}), 403  # Forbidden

            session['db_user_id'] = user.id
            session['user_info'] = {
                'name': user.name,
                'email': user.email,
                'picture': user.picture_url,
                'is_admin': user.is_admin
            }
            return jsonify({"success": True, "message": "Đăng nhập thành công!"})
        else:
            return jsonify({"success": False, "message": "Email hoặc mật khẩu không đúng."}), 401  # Unauthorized

    # GET request đến /login (ví dụ, gõ trực tiếp URL) sẽ redirect về home, modal sẽ mở bằng JS nếu có param
    return redirect(url_for('home', open_login_modal='true'))


# --- Route Đăng ký ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if session.get("db_user_id") or google.authorized:  # Nếu đã đăng nhập thì về home
        return redirect(url_for('home'))

    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if not name or not email or not password or not confirm_password:
            flash('Vui lòng điền đầy đủ thông tin.', 'danger')
            return redirect(url_for('register'))

        if password != confirm_password:
            flash('Mật khẩu và xác nhận mật khẩu không khớp.', 'danger')
            return redirect(url_for('register'))

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Địa chỉ email này đã được sử dụng.', 'warning')
            return redirect(url_for('register'))

        new_user = User(name=name, email=email)
        new_user.set_password(password)  # Hash mật khẩu

        try:
            db.session.add(new_user)
            db.session.commit()
            flash('Đăng ký thành công! Vui lòng đăng nhập.', 'success')
            return redirect(url_for('login'))  # Chuyển đến trang đăng nhập
        except Exception as e:
            db.session.rollback()
            flash(f'Đã xảy ra lỗi khi đăng ký: {str(e)}', 'danger')
            print(f"Error during registration: {e}")  # Ghi log lỗi
            return redirect(url_for('register'))

    return render_template('register.html')


# Các route khác
@app.route('/privacy-policy')
def privacy_policy_page():
    return "<h1>Chính sách Bảo mật (Privacy Policy)</h1><p>Nội dung sẽ được cập nhật sớm.</p>"


@app.route('/terms-of-service')
def terms_of_service_page():
    return "<h1>Điều khoản Dịch vụ (Terms of Service)</h1><p>Nội dung sẽ được cập nhật sớm.</p>"


def translate_with_deep_translator(text_to_translate, dest_lang='vi', src_lang='auto'):
    if not text_to_translate or not isinstance(text_to_translate, str) or not text_to_translate.strip():
        return text_to_translate

    api_name = "deep_translator_google"
    user_id_to_log = session.get("db_user_id")  # Lấy user_id từ session nếu có
    log_entry = APILog(api_name=api_name, request_details=f"Text: {text_to_translate[:100]}...",
                       user_id=user_id_to_log)  # Chuẩn bị log entry

    try:
        translated_text = GoogleTranslator(source=src_lang, target=dest_lang).translate(text_to_translate)

        if translated_text is None:
            log_entry.success = False
            log_entry.error_message = "Translation returned None"
            print(f"deep-translator: Dịch trả về None cho '{text_to_translate[:50]}...'")
            db.session.add(log_entry)  # Vẫn ghi log dù lỗi
            db.session.commit()
            return text_to_translate

        log_entry.success = True
        # log_entry.status_code = 200 # Giả định thành công là 200, API này không trả trực tiếp status code qua thư viện
        print(f"deep-translator: Dịch thành công: '{translated_text[:50]}...'")
        db.session.add(log_entry)
        db.session.commit()
        return translated_text

    except Exception as e:
        log_entry.success = False
        log_entry.error_message = str(e)[:500]  # Giới hạn độ dài lỗi
        print(f"Lỗi khi dùng deep-translator cho '{text_to_translate[:50]}...': {e}")
        db.session.add(log_entry)
        db.session.commit()
        return text_to_translate


# --- Hàm trợ giúp gọi API LibreTranslate ---
def translate_text_libre_batch(texts_to_translate, target_lang="vi", source_lang="en"):
    if not texts_to_translate:
        return []

    LIBRETRANSLATE_API_URL = "https://libretranslate.de/translate"
    payload = {"q": texts_to_translate, "source": source_lang, "target": target_lang, "format": "text"}
    headers = {"Content-Type": "application/json"}

    # Tăng thời gian chờ cố định lên, ví dụ 45 giây
    # Nếu bạn dịch ít từ (ví dụ 1-5 từ, mỗi từ 1 định nghĩa), 30-45s có thể đủ.
    # Nếu nhiều hơn, có thể cần tăng thêm hoặc xem xét chia nhỏ batch hơn nữa.
    timeout_duration = 45  # Thử với 45 giây

    try:
        print(
            f"Đang gửi batch translation request với timeout: {timeout_duration}s cho {len(texts_to_translate)} câu.")  # Debug
        response = requests.post(LIBRETRANSLATE_API_URL, json=payload, headers=headers, timeout=timeout_duration)
        response.raise_for_status()
        data = response.json()
        translated_texts_list = data.get("translatedTexts")

        if translated_texts_list and len(translated_texts_list) == len(texts_to_translate):
            print("Dịch batch thành công!")  # Debug
            return translated_texts_list
        else:
            print(f"Lỗi dịch batch: Không tìm thấy 'translatedTexts' hoặc số lượng không khớp. Response: {data}")
            return [text for text in texts_to_translate]

    except requests.exceptions.Timeout:
        print(f"Timeout ({timeout_duration}s) khi dịch batch cho: {texts_to_translate}")
        return [text for text in texts_to_translate]
    except requests.exceptions.RequestException as e:
        print(f"Lỗi Request API trong khi dịch batch: {e}")
        return [text for text in texts_to_translate]
    except Exception as e:
        print(f"Lỗi không mong muốn trong khi dịch batch: {e}")
        return [text for text in texts_to_translate]


def translate_single_text_libre(text_to_translate, target_lang="vi", source_lang="en",
                                timeout=20):  # Timeout cho một câu, ví dụ 20s
    if not text_to_translate or not text_to_translate.strip():
        return text_to_translate  # Trả về gốc nếu rỗng hoặc toàn khoảng trắng

    LIBRETRANSLATE_API_URL = "https://libretranslate.de/translate"
    # Hoặc một instance khác bạn muốn thử:
    # LIBRETRANSLATE_API_URL = "https://translate.argosopentech.com/translate" # API này có cấu trúc payload và response khác một chút

    payload = {"q": text_to_translate, "source": source_lang, "target": target_lang, "format": "text"}

    try:
        # print(f"Đang dịch đơn lẻ: '{text_to_translate[:30]}...' với timeout {timeout}s") # Debug
        response = requests.post(LIBRETRANSLATE_API_URL, data=payload,
                                 timeout=timeout)  # libretranslate.de dùng data=payload
        response.raise_for_status()
        data = response.json()
        translated_text = data.get("translatedText")
        if translated_text:
            # print(f"Dịch đơn lẻ thành công: '{translated_text[:30]}...'") # Debug
            return translated_text
        else:
            print(
                f"Không tìm thấy 'translatedText' trong phản hồi đơn lẻ cho '{text_to_translate[:30]}...'. Phản hồi: {data}")
            return text_to_translate
    except requests.exceptions.Timeout:
        print(f"Timeout ({timeout}s) khi dịch đơn lẻ: '{text_to_translate[:30]}...'")
        return text_to_translate
    except Exception as e:
        print(f"Lỗi khi dịch đơn lẻ '{text_to_translate[:30]}...': {e}")
        return text_to_translate


def get_word_details_dictionaryapi(word):
    DICTIONARY_API_URL = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
    detailed_entries = []

    api_name = "dictionary_api"
    user_id_to_log = session.get("db_user_id")
    log_entry = APILog(api_name=api_name, request_details=f"Word: {word}", user_id=user_id_to_log,
                       success=False)  # Mặc định là False

    try:
        response = requests.get(DICTIONARY_API_URL, timeout=15)
        log_entry.status_code = response.status_code
        response.raise_for_status()
        data = response.json()

        if isinstance(data, list) and len(data) > 0:
            for entry_data in data:
                if entry_data.get("meanings"):
                    for meaning_obj in entry_data["meanings"]:
                        part_of_speech = meaning_obj.get("partOfSpeech", "N/A")
                        if meaning_obj.get("definitions"):
                            for definition_obj_item in meaning_obj["definitions"]:
                                definition_en = definition_obj_item.get("definition")
                                example_en = definition_obj_item.get("example")

                                if definition_en:
                                    detailed_entries.append({
                                        "type": part_of_speech,
                                        "definition_en": definition_en,
                                        "example_en": example_en if example_en else "N/A"
                                    })
                                    log_entry.success = True  # Đánh dấu thành công nếu tìm thấy định nghĩa
                                    # Chỉ trả về 1 định nghĩa đầu tiên
                                    # Việc ghi log sẽ diễn ra ở khối finally
                                    return detailed_entries

                                    # Nếu không có definition_en nào được tìm thấy trong các vòng lặp
            log_entry.error_message = "No valid definitions found in API response structure."
            print(f"No definitions with content found for '{word}'.")
        else:
            log_entry.error_message = "No detailed entry found or unexpected format from API."
            print(f"No detailed entry found or unexpected format for '{word}'.")

    except requests.exceptions.Timeout as e:
        log_entry.error_message = f"Timeout: {str(e)}"
        print(f"Timeout when calling Dictionary API for '{word}'.")
    except requests.exceptions.HTTPError as http_err:
        # log_entry.status_code đã được set ở trên nếu response nhận được
        log_entry.error_message = f"HTTP Error: {str(http_err)}"
        print(f"Lỗi HTTP khi gọi Dictionary API cho từ '{word}': {http_err}")
    except requests.exceptions.RequestException as e:
        log_entry.error_message = f"Request Error: {str(e)}"
        print(f"Lỗi Request API cho từ '{word}' với Dictionary API: {e}")
    except Exception as e:  # Bao gồm lỗi parsing JSON nếu data không phải JSON hợp lệ
        log_entry.error_message = f"Unexpected Error: {str(e)}"
        print(f"Lỗi không mong muốn khi lấy chi tiết cho từ '{word}': {e}")
    finally:
        # Luôn ghi log vào database
        db.session.add(log_entry)
        db.session.commit()

    return detailed_entries


@app.route('/enter-words', methods=['GET', 'POST'])  # Sửa lại để route này xử lý cả POST cho generate
def enter_words_page():
    display_user_info = get_current_user_info()
    user_lists = []  # Danh sách hiện có của user (cho modal)
    target_list_info = None  # Thông tin về list đang được nhắm đến (nếu có)

    # Luôn lấy danh sách list của user nếu đã đăng nhập (cho modal save)
    if display_user_info and session.get("db_user_id"):
        current_user_db_id = session.get("db_user_id")
        user_lists = VocabularyList.query.filter_by(user_id=current_user_db_id).order_by(
            VocabularyList.name.asc()).all()

    # Xử lý nếu có target_list_id từ URL (khi người dùng nhấn "Add Words" từ my_lists)
    if request.method == 'GET':
        target_list_id_from_url = request.args.get('target_list_id', type=int)
        if target_list_id_from_url and display_user_info:  # Chỉ xử lý nếu user đã login
            current_user_db_id = session.get("db_user_id")
            # Kiểm tra xem list này có thuộc về user không
            list_obj = VocabularyList.query.filter_by(id=target_list_id_from_url, user_id=current_user_db_id).first()
            if list_obj:
                target_list_info = {"id": list_obj.id, "name": list_obj.name}
                flash(f"Bạn đang thêm từ vào danh sách: '{list_obj.name}'. Các từ sẽ được lưu vào danh sách này.",
                      "info")
            else:
                flash("Không tìm thấy danh sách được chỉ định hoặc bạn không có quyền.", "warning")

    input_str = request.form.get('words_input', '') if request.method == 'POST' else session.get('last_processed_input',
                                                                                                 '')
    processed_results_dict = {}

    if request.method == 'POST':
        # ... (Toàn bộ logic xử lý POST (Generate) của bạn giữ nguyên như trước) ...
        # (Lấy words_list, gọi API dịch, API từ điển, xây dựng processed_results_dict)
        session['last_processed_input'] = input_str
        words_list = []
        if input_str:
            words_list = [word.strip() for word in input_str.split(',') if word.strip()]

        if words_list:
            # (Logic gọi API và xây dựng processed_results_dict của bạn ở đây)
            # Ví dụ:
            temp_word_details_map = {}
            all_english_definitions_to_translate = []
            original_word_for_each_definition = []

            for original_word in words_list:
                detailed_entries = get_word_details_dictionaryapi(original_word)
                temp_word_details_map[original_word] = []
                if detailed_entries:
                    for entry in detailed_entries:
                        all_english_definitions_to_translate.append(entry["definition_en"])
                        original_word_for_each_definition.append(original_word)
                        temp_word_details_map[original_word].append(entry)
                else:
                    all_english_definitions_to_translate.append(original_word)
                    original_word_for_each_definition.append(original_word)
                    temp_word_details_map[original_word].append({
                        "type": "N/A", "definition_en": original_word, "example_en": "N/A"
                    })

            translated_definitions_vi = []
            if all_english_definitions_to_translate:
                translated_definitions_vi = translate_with_deep_translator(
                    all_english_definitions_to_translate)  # Giả sử hàm này xử lý batch hoặc list

            translation_idx_counter = 0
            for original_word in words_list:
                processed_results_dict[original_word] = []
                if original_word in temp_word_details_map:
                    for entry_detail in temp_word_details_map[original_word]:
                        vietnamese_explanation = "Lỗi dịch hoặc không có định nghĩa."
                        if translation_idx_counter < len(translated_definitions_vi):
                            vietnamese_explanation = translated_definitions_vi[translation_idx_counter]

                        processed_results_dict[original_word].append({
                            "type": entry_detail["type"],
                            "definition_en": entry_detail["definition_en"],
                            "definition_vi": vietnamese_explanation,
                            "example_sentence": entry_detail["example_en"]
                        })
                        translation_idx_counter += 1
        elif input_str:
            flash("Vui lòng nhập từ hợp lệ.", "info")

        # Không xóa session input ở đây nếu muốn giữ lại sau khi generate
        # session.pop('last_processed_input', None) # Tạm thời comment lại

    # Xử lý input_str cho GET request để giữ lại nếu có lỗi POST trước đó
    if request.method == 'GET' and not target_list_info:  # Chỉ xóa nếu không phải là redirect từ my_lists và không có kết quả cũ
        input_str_from_session = session.pop('last_processed_input', '')
        if not input_str:  # Nếu URL không có param (ví dụ, vào thẳng /enter-words)
            input_str = input_str_from_session

    return render_template('enter_words.html',
                           user_info=display_user_info,
                           input_words_str=input_str,  # Giữ lại từ đã nhập
                           results=processed_results_dict,
                           user_existing_lists=user_lists,  # Cho modal save
                           target_list_info=target_list_info)  # Thông tin list đang nhắm đến


@app.route('/save-list', methods=['POST'])  # Đổi tên cho nhất quán với JS: save_list_route
def save_list_route():  # Đổi tên hàm cho nhất quán
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:
        return jsonify({"success": False, "message": "Vui lòng đăng nhập."}), 401

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Không nhận được dữ liệu."}), 400

    vocabulary_items_data = data.get('words')  # JS đang gửi là 'words'
    list_name_from_input = data.get('list_name')  # Cho list mới
    existing_list_id = data.get('existing_list_id')  # Cho list đã có

    if not vocabulary_items_data or not isinstance(vocabulary_items_data, list) or len(vocabulary_items_data) == 0:
        return jsonify({"success": False, "message": "Không có từ vựng nào để lưu."}), 400

    target_list = None

    if existing_list_id:
        # Người dùng muốn thêm vào list đã có
        target_list = VocabularyList.query.filter_by(id=existing_list_id, user_id=current_user_db_id).first()
        if not target_list:
            return jsonify(
                {"success": False, "message": "Không tìm thấy danh sách hiện có hoặc bạn không có quyền."}), 403
    elif list_name_from_input and list_name_from_input.strip():
        # Người dùng muốn tạo list mới
        target_list = VocabularyList(name=list_name_from_input.strip(), user_id=current_user_db_id)
        db.session.add(target_list)
        # Cần flush để target_list có ID nếu các entry cần nó ngay lập tức,
        # nhưng với backref thì SQLAlchemy có thể tự xử lý khi commit.
    else:
        # Không có existing_list_id và cũng không có list_name hợp lệ
        return jsonify({"success": False,
                        "message": "Vui lòng cung cấp tên cho danh sách mới hoặc chọn một danh sách hiện có."}), 400

    try:
        # Thêm các VocabularyEntry
        for item_data in vocabulary_items_data:
            new_entry = VocabularyEntry(
                original_word=item_data.get('original_word'),
                word_type=item_data.get('word_type'),
                definition_en=item_data.get('definition_en'),
                definition_vi=item_data.get('definition_vi'),
                example_en=item_data.get('example_en'),
                user_id=current_user_db_id,  # Luôn gán user_id cho entry
                vocabulary_list=target_list  # Liên kết với list (mới hoặc đã có)
            )
            db.session.add(new_entry)

        db.session.commit()

        action_message = f"Đã thêm từ vào danh sách '{target_list.name}'." if existing_list_id else f"Đã tạo và lưu danh sách '{target_list.name}'."
        return jsonify({"success": True, "message": action_message})

    except Exception as e:
        db.session.rollback()
        print(f"Lỗi khi lưu danh sách/từ: {e}")
        return jsonify({"success": False, "message": f"Lỗi server: {str(e)}"}), 500


@app.route('/my-lists')
def my_lists_page():
    # 1. Kiểm tra xem người dùng đã đăng nhập chưa
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:
        flash("Vui lòng đăng nhập để xem danh sách của bạn.", "warning")
        # Nếu login modal hoạt động tốt, có thể không cần redirect mà để base.html xử lý nút đăng nhập
        # Hoặc bạn có thể mở login modal từ đây bằng một cách nào đó (ví dụ: redirect về home với param để mở modal)
        return redirect(url_for('home'))  # Tạm thời redirect về home

    # 2. Lấy thông tin người dùng hiện tại để hiển thị trên trang (ví dụ: avatar ở header)
    display_user_info = get_current_user_info()

    # 3. Truy vấn database để lấy tất cả các VocabularyList của người dùng hiện tại
    # Sắp xếp theo ngày tạo mới nhất lên đầu (tùy chọn)
    user_lists = VocabularyList.query.filter_by(user_id=current_user_db_id).order_by(
        VocabularyList.created_at.desc()).all()

    print(f"Đang hiển thị {len(user_lists)} danh sách cho user_id {current_user_db_id}")  # Debug

    return render_template('my_lists.html',
                           user_info=display_user_info,
                           my_vocabulary_lists=user_lists)


@app.route('/my-lists/<int:list_id>')
def list_detail_page(list_id):
    # 1. Kiểm tra đăng nhập
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:
        flash("Vui lòng đăng nhập để xem chi tiết danh sách.", "warning")
        return redirect(url_for('home'))

    # 2. Lấy thông tin người dùng hiện tại
    display_user_info = get_current_user_info()

    # 3. Lấy đối tượng VocabularyList từ database
    # Đảm bảo list này thuộc về người dùng hiện tại để bảo mật
    vocab_list = VocabularyList.query.filter_by(id=list_id, user_id=current_user_db_id).first()

    if not vocab_list:
        flash("Không tìm thấy danh sách từ vựng hoặc bạn không có quyền truy cập.", "danger")
        return redirect(url_for('my_lists_page'))  # Chuyển hướng về trang danh sách

    # 4. Lấy tất cả các VocabularyEntry thuộc về VocabularyList này
    # entries đã được định nghĩa trong model VocabularyList qua db.relationship
    # và chúng ta có thể sắp xếp chúng, ví dụ theo original_word hoặc added_at
    entries_in_list = VocabularyEntry.query.filter_by(list_id=vocab_list.id).order_by(
        VocabularyEntry.added_at.asc()).all()
    # Thêm dòng print này để kiểm tra
    print(f"Số lượng entries cho list {vocab_list.id}: {len(entries_in_list)}")
    if entries_in_list:
        print(f"Entry đầu tiên: {entries_in_list[0].original_word}")

    return render_template('list_detail.html',
                           user_info=display_user_info,
                           current_list=vocab_list,
                           entries=entries_in_list)  # Đảm bảo biến này tên là 'entries'


@app.route('/delete-list/<int:list_id>', methods=['POST'])
def delete_list_route(list_id):
    # 1. Kiểm tra đăng nhập
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:
        flash("Vui lòng đăng nhập để thực hiện hành động này.", "warning")
        return redirect(url_for('home'))  # Hoặc trang login nếu có

    # 2. Tìm VocabularyList cần xóa
    list_to_delete = VocabularyList.query.get(list_id)  # Lấy bằng ID

    if not list_to_delete:
        flash("Không tìm thấy danh sách để xóa.", "danger")
        return redirect(url_for('my_lists_page'))

    # 3. Kiểm tra xem danh sách có thuộc về người dùng hiện tại không
    if list_to_delete.user_id != current_user_db_id:
        flash("Bạn không có quyền xóa danh sách này.", "danger")
        return redirect(url_for('my_lists_page'))

    try:
        # Xóa danh sách. Nhờ 'cascade="all, delete-orphan"' trong model VocabularyList,
        # tất cả các VocabularyEntry liên quan cũng sẽ bị xóa.
        db.session.delete(list_to_delete)
        db.session.commit()
        flash(f"Đã xóa thành công danh sách '{list_to_delete.name}'.", "success")
        print(f"User {current_user_db_id} đã xóa list ID {list_id} ('{list_to_delete.name}')")  # Debug
    except Exception as e:
        db.session.rollback()
        flash(f"Có lỗi xảy ra khi xóa danh sách: {str(e)}", "danger")
        print(f"Lỗi khi user {current_user_db_id} xóa list ID {list_id}: {e}")  # Debug

    return redirect(url_for('my_lists_page'))  # Quay lại trang danh sách


@app.route('/rename-list/<int:list_id>', methods=['POST'])
def rename_list_route(list_id):
    if not session.get("db_user_id"):
        return jsonify({"success": False, "message": "Vui lòng đăng nhập."}), 401

    current_user_db_id = session.get("db_user_id")

    list_to_rename = VocabularyList.query.get(list_id)

    if not list_to_rename:
        return jsonify({"success": False, "message": "Không tìm thấy danh sách."}), 404

    if list_to_rename.user_id != current_user_db_id:
        return jsonify({"success": False, "message": "Bạn không có quyền sửa danh sách này."}), 403

    data = request.get_json()
    new_name = data.get('new_name', '').strip()

    if not new_name:
        return jsonify({"success": False, "message": "Tên danh sách mới không được để trống."}), 400

    try:
        list_to_rename.name = new_name
        db.session.commit()
        flash(f"Đã đổi tên danh sách thành '{new_name}'.", "success")  # Flash message cho lần tải lại trang
        return jsonify({"success": True, "message": "Đổi tên thành công!"})
    except Exception as e:
        db.session.rollback()
        print(f"Lỗi khi đổi tên list ID {list_id}: {e}")
        return jsonify({"success": False, "message": f"Lỗi server: {str(e)}"}), 500


@app.route('/delete-entry/<int:entry_id>', methods=['POST'])
def delete_entry_route(entry_id):
    # 1. Kiểm tra đăng nhập
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:
        flash("Vui lòng đăng nhập để thực hiện hành động này.", "warning")
        # Trong trường hợp này, không rõ nên redirect về đâu nếu không có list_id
        # Tốt nhất là redirect về trang chủ hoặc trang đăng nhập
        return redirect(url_for('home'))

    # 2. Tìm VocabularyEntry cần xóa
    entry_to_delete = VocabularyEntry.query.get(entry_id)

    if not entry_to_delete:
        flash("Không tìm thấy từ để xóa.", "danger")
        # Cần list_id để redirect về trang chi tiết list cũ, nếu không có thì về trang my_lists
        # Nếu entry_to_delete không tồn tại, chúng ta không có list_id từ nó.
        # Cách tốt hơn là truyền list_id từ form hoặc lấy từ referer.
        # Tạm thời redirect về my_lists_page
        return redirect(url_for('my_lists_page'))

    # 3. Lấy list_id để redirect lại sau khi xóa
    parent_list_id = entry_to_delete.list_id

    # 4. Kiểm tra xem entry này có thuộc về người dùng hiện tại không
    # (Thông qua việc kiểm tra list cha của entry đó có thuộc về user không)
    if entry_to_delete.vocabulary_list.user_id != current_user_db_id:
        flash("Bạn không có quyền xóa từ này.", "danger")
        return redirect(url_for('list_detail_page', list_id=parent_list_id))

    try:
        db.session.delete(entry_to_delete)
        db.session.commit()
        flash(f"Đã xóa thành công từ '{entry_to_delete.original_word}'.", "success")
        print(
            f"User {current_user_db_id} đã xóa entry ID {entry_id} ('{entry_to_delete.original_word}') khỏi list ID {parent_list_id}")  # Debug
    except Exception as e:
        db.session.rollback()
        flash(f"Có lỗi xảy ra khi xóa từ: {str(e)}", "danger")
        print(f"Lỗi khi user {current_user_db_id} xóa entry ID {entry_id}: {e}")  # Debug

    # Redirect trở lại trang chi tiết của danh sách mà từ đó vừa bị xóa
    return redirect(url_for('list_detail_page', list_id=parent_list_id))


# File: app.py
# ... (các import, models, hàm get_current_user_info, và các route khác của bạn) ...

@app.route('/profile', methods=['GET', 'POST'])
def profile_page():
    # 1. Kiểm tra đăng nhập
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:
        flash("Vui lòng đăng nhập để xem hồ sơ của bạn.", "warning")
        return redirect(url_for('home'))

    # 2. Lấy đối tượng User từ database
    user = User.query.get(current_user_db_id)
    if not user:
        flash("Không tìm thấy thông tin người dùng.", "danger")
        session.clear()  # Xóa session hỏng nếu có
        return redirect(url_for('home'))

    # 3. Xử lý việc cập nhật/đặt mật khẩu nếu là POST request
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not new_password or not confirm_password:
            flash("Vui lòng nhập mật khẩu mới và xác nhận mật khẩu.", "danger")
        elif new_password != confirm_password:
            flash("Mật khẩu mới và xác nhận mật khẩu không khớp.", "danger")
        elif len(new_password) < 6:  # Thêm kiểm tra độ dài mật khẩu cơ bản
            flash("Mật khẩu mới phải có ít nhất 6 ký tự.", "danger")
        else:
            try:
                user.set_password(new_password)  # Hàm này sẽ hash mật khẩu
                db.session.commit()
                flash("Đã cập nhật/đặt mật khẩu thành công!", "success")
                print(f"User {user.email} đã cập nhật mật khẩu.")  # Debug
            except Exception as e:
                db.session.rollback()
                flash(f"Có lỗi xảy ra khi cập nhật mật khẩu: {str(e)}", "danger")
                print(f"Lỗi khi user {user.email} cập nhật mật khẩu: {e}")  # Debug

        return redirect(url_for('profile_page'))  # Redirect để tránh submit lại form khi refresh

    # 4. Lấy thông tin để hiển thị (cho GET request hoặc sau khi POST)
    # display_user_info nên lấy từ đối tượng user đã query từ DB
    display_user_info = {
        "name": user.name,
        "email": user.email,
        "picture": user.picture_url,
        "has_password": bool(user.password_hash),
        "google_id": user.google_id
    }

    return render_template('profile.html',
                           user_profile_info=display_user_info)


@app.route('/admin')
@app.route('/admin/dashboard')  # Thêm một URL nữa cho dashboard nếu muốn
@admin_required  # Áp dụng decorator để bảo vệ route này
def admin_dashboard():
    display_user_info = get_current_user_info()  # Để base.html hiển thị đúng header

    # Truy vấn tất cả người dùng để hiển thị
    all_users = User.query.order_by(User.created_at.desc()).all()  # Lấy tất cả user, sắp xếp theo ngày tạo

    return render_template('admin/dashboard.html',
                           user_info=display_user_info,
                           users_list=all_users)


@app.route('/admin/user/<int:user_id_to_view>')
@admin_required
def admin_view_user_detail(user_id_to_view):
    # 1. Lấy thông tin admin hiện tại để hiển thị trên trang (ví dụ: avatar ở header của base.html)
    admin_user_info = get_current_user_info()

    # 2. Lấy đối tượng User cần xem từ database
    user_to_view = User.query.get_or_404(user_id_to_view)
    # get_or_404 sẽ tự động trả về lỗi 404 Not Found nếu không tìm thấy user với ID đó

    # 3. Lấy tất cả các VocabularyList của người dùng này
    # Sắp xếp theo ngày tạo mới nhất lên đầu (tùy chọn)
    user_vocabulary_lists = VocabularyList.query.filter_by(user_id=user_to_view.id).order_by(
        VocabularyList.created_at.desc()).all()

    print(
        f"Admin đang xem chi tiết user '{user_to_view.email}' (ID: {user_id_to_view}) với {len(user_vocabulary_lists)} danh sách.")  # Debug

    return render_template('admin/user_detail.html',
                           user_info=admin_user_info,  # Thông tin của admin đang đăng nhập (cho base.html)
                           viewed_user=user_to_view,  # Thông tin của người dùng đang được xem
                           vocabulary_lists_of_user=user_vocabulary_lists)  # Danh sách từ vựng của người dùng đó


@app.route('/admin/delete-user/<int:user_id_to_delete>', methods=['POST'])
@admin_required
def admin_delete_user_route(user_id_to_delete):
    admin_user_id = session.get("db_user_id")

    if user_id_to_delete == admin_user_id:
        flash("Bạn không thể tự xóa tài khoản của chính mình.", "danger")
        return redirect(url_for('admin_dashboard'))

    user_to_delete = User.query.get(user_id_to_delete)

    if not user_to_delete:
        flash("Không tìm thấy người dùng để xóa.", "danger")
        return redirect(url_for('admin_dashboard'))

    # Thêm một lớp bảo vệ nữa: không cho phép xóa admin khác từ giao diện này
    # (trừ khi bạn muốn có cơ chế cho super-admin, nhưng hiện tại để an toàn)
    if user_to_delete.is_admin:
        flash("Không thể xóa tài khoản Admin từ giao diện này.", "danger")
        return redirect(url_for('admin_view_user_detail', user_id_to_view=user_id_to_delete))

    try:
        user_email_deleted = user_to_delete.email  # Lấy email để thông báo

        # Nhờ cascade="all, delete-orphan" trên User.vocabulary_lists
        # và trên VocabularyList.entries, các list và entry liên quan sẽ bị xóa.
        db.session.delete(user_to_delete)
        db.session.commit()

        flash(f"Đã xóa thành công người dùng '{user_email_deleted}' và tất cả dữ liệu liên quan.", "success")
        print(f"Admin {admin_user_id} đã xóa user ID {user_id_to_delete} ('{user_email_deleted}')")  # Debug
        return redirect(url_for('admin_dashboard'))

    except Exception as e:
        db.session.rollback()
        flash(f"Có lỗi xảy ra khi xóa người dùng: {str(e)}", "danger")
        print(f"Lỗi khi Admin {admin_user_id} xóa user ID {user_id_to_delete}: {e}")  # Debug
        return redirect(url_for('admin_view_user_detail', user_id_to_view=user_id_to_delete))


@app.route('/admin/user/<int:user_id_to_toggle>/toggle-block', methods=['POST'])
@admin_required
def admin_toggle_block_user_route(user_id_to_toggle):
    admin_user_id = session.get("db_user_id")

    if user_id_to_toggle == admin_user_id:
        flash("Bạn không thể tự chặn/bỏ chặn chính mình.", "danger")
        return redirect(request.referrer or url_for('admin_dashboard'))  # Quay lại trang trước đó hoặc dashboard

    user_to_toggle = User.query.get_or_404(user_id_to_toggle)

    if user_to_toggle.is_admin:
        flash("Không thể chặn/bỏ chặn tài khoản Admin khác.", "danger")
        return redirect(request.referrer or url_for('admin_dashboard'))

    try:
        user_to_toggle.is_blocked = not user_to_toggle.is_blocked  # Đảo ngược trạng thái
        db.session.commit()
        action = "bỏ chặn" if not user_to_toggle.is_blocked else "chặn"
        flash(f"Đã {action} thành công người dùng '{user_to_toggle.email}'.", "success")
        print(f"Admin {admin_user_id} đã {action} user ID {user_id_to_toggle} ('{user_to_toggle.email}')")  # Debug
    except Exception as e:
        db.session.rollback()
        flash(f"Có lỗi xảy ra khi thay đổi trạng thái người dùng: {str(e)}", "danger")
        print(f"Lỗi khi Admin {admin_user_id} toggle block user ID {user_id_to_toggle}: {e}")  # Debug

    # Quay lại trang chi tiết user nếu đang ở đó, hoặc về dashboard
    if request.referrer and f'/admin/user/{user_id_to_toggle}' in request.referrer:
        return redirect(url_for('admin_view_user_detail', user_id_to_view=user_id_to_toggle))
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/user/<int:owner_user_id>/list/<int:list_id>')
@admin_required
def admin_view_list_entries_page(owner_user_id, list_id):
    # 1. Lấy thông tin admin hiện tại (cho base.html)
    admin_user_info = get_current_user_info()

    # 2. Lấy thông tin người dùng sở hữu danh sách này (để hiển thị)
    list_owner = User.query.get(owner_user_id)
    if not list_owner:
        flash(f"Không tìm thấy người dùng với ID {owner_user_id}.", "danger")
        return redirect(url_for('admin_dashboard'))

    # 3. Lấy đối tượng VocabularyList từ database
    # Kiểm tra xem list này có thực sự thuộc về owner_user_id không
    vocab_list = VocabularyList.query.filter_by(id=list_id, user_id=owner_user_id).first()

    if not vocab_list:
        flash(
            f"Không tìm thấy danh sách từ vựng với ID {list_id} cho người dùng {list_owner.email}, hoặc bạn không có quyền truy cập.",
            "danger")
        # Chuyển hướng về trang chi tiết của người dùng đó trong admin
        return redirect(url_for('admin_view_user_detail', user_id_to_view=owner_user_id))

    # 4. Lấy tất cả các VocabularyEntry thuộc về VocabularyList này
    entries_in_list = VocabularyEntry.query.filter_by(list_id=vocab_list.id).order_by(
        VocabularyEntry.added_at.asc()).all()

    print(
        f"Admin đang xem chi tiết list '{vocab_list.name}' (ID: {list_id}) của user '{list_owner.email}' với {len(entries_in_list)} từ.")  # Debug

    return render_template('admin/admin_list_entries.html',
                           user_info=admin_user_info,  # Info của Admin đang login
                           current_list=vocab_list,  # Đối tượng VocabularyList đang xem
                           list_owner=list_owner,  # Đối tượng User sở hữu list
                           entries=entries_in_list)  # Danh sách các từ trong list


@app.route('/admin/entry/<int:entry_id>/delete', methods=['POST'])
@admin_required
def admin_delete_vocab_entry_route(entry_id):
    admin_user_info = get_current_user_info()  # Thông tin admin đang đăng nhập

    entry_to_delete = VocabularyEntry.query.get(entry_id)

    if not entry_to_delete:
        flash("Không tìm thấy mục từ vựng để xóa.", "danger")
        # Cố gắng redirect về trang trước đó nếu có, nếu không thì về admin dashboard
        return redirect(request.referrer or url_for('admin_dashboard'))

    # Lấy thông tin list và owner từ entry TRƯỚC KHI xóa, để redirect lại đúng trang
    parent_list_id = entry_to_delete.list_id
    # Chúng ta cần owner_id của list đó để tạo URL cho admin_view_list_entries_page
    parent_list_owner_id = entry_to_delete.vocabulary_list.user_id

    entry_original_word = entry_to_delete.original_word  # Lấy tên từ để thông báo

    try:
        db.session.delete(entry_to_delete)
        db.session.commit()
        flash(f"Đã xóa thành công mục từ '{entry_original_word}' khỏi danh sách.", "success")
        print(
            f"Admin {admin_user_info.get('email')} đã xóa entry ID {entry_id} ('{entry_original_word}') khỏi list ID {parent_list_id}")  # Debug
    except Exception as e:
        db.session.rollback()
        flash(f"Có lỗi xảy ra khi xóa mục từ: {str(e)}", "danger")
        print(f"Lỗi khi Admin {admin_user_info.get('email')} xóa entry ID {entry_id}: {e}")  # Debug

    # Redirect trở lại trang admin xem chi tiết list mà từ đó vừa bị xóa
    return redirect(url_for('admin_view_list_entries_page', owner_user_id=parent_list_owner_id, list_id=parent_list_id))


@app.route('/admin/entry/<int:entry_id>/edit', methods=['POST'])
@admin_required
def admin_edit_vocab_entry_route(entry_id):
    entry_to_edit = VocabularyEntry.query.get_or_404(entry_id)
    admin_user_info = get_current_user_info()  # Lấy thông tin admin cho logging

    # Admin có quyền sửa bất kỳ entry nào, không cần kiểm tra user_id của entry,
    # vì họ đã qua @admin_required và đang ở trong khu vực quản lý.
    # Tuy nhiên, nếu muốn thêm lớp kiểm tra (ví dụ: admin cấp thấp hơn chỉ sửa được một số loại nhất định),
    # thì có thể thêm ở đây.

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Không có dữ liệu được gửi."}), 400

    try:
        # Cập nhật các trường có thể sửa đổi
        # original_word thường không nên cho sửa, nếu sửa thì coi như là entry mới.
        entry_to_edit.word_type = data.get('word_type', entry_to_edit.word_type)
        entry_to_edit.definition_en = data.get('definition_en', entry_to_edit.definition_en)
        entry_to_edit.definition_vi = data.get('definition_vi', entry_to_edit.definition_vi)
        entry_to_edit.example_en = data.get('example_en', entry_to_edit.example_en)
        # Cập nhật thêm trường last_modified_by_admin, last_modified_at nếu có trong model

        db.session.commit()
        flash(f"Đã cập nhật thành công mục từ '{entry_to_edit.original_word}'.", "success")  # Sẽ hiển thị khi reload
        print(f"Admin {admin_user_info.get('email')} đã sửa entry ID {entry_id} ('{entry_to_edit.original_word}')")
        return jsonify({"success": True, "message": "Cập nhật thành công!"})

    except Exception as e:
        db.session.rollback()
        print(f"Lỗi khi Admin {admin_user_info.get('email')} sửa entry ID {entry_id}: {e}")
        return jsonify({"success": False, "message": f"Lỗi server: {str(e)}"}), 500


@app.route('/admin/api-logs')
@admin_required
def admin_api_logs_page():
    admin_user_info = get_current_user_info()  # Lấy thông tin admin cho base template

    # Lấy tất cả logs, sắp xếp theo thời gian mới nhất lên đầu
    # Có thể thêm phân trang ở đây sau này nếu log quá nhiều
    logs = APILog.query.order_by(APILog.timestamp.desc()).limit(200).all()  # Giới hạn 200 log gần nhất

    # Tính toán một số thống kê cơ bản
    total_calls = APILog.query.count()
    successful_calls = APILog.query.filter_by(success=True).count()
    failed_calls = total_calls - successful_calls

    calls_by_api_name = db.session.query(
        APILog.api_name,
        func.count(APILog.api_name).label('count'),
        func.sum(case((APILog.success == True, 1), else_=0)).label('successful'),  # Cần import case từ sqlalchemy.sql
        func.sum(case((APILog.success == False, 1), else_=0)).label('failed')
    ).group_by(APILog.api_name).all()
    # Để dùng case, cần import: from sqlalchemy.sql import case
    # Nếu cách trên phức tạp, có thể query riêng cho từng loại:
    # calls_by_api_name_simple = {}
    # distinct_api_names = db.session.query(APILog.api_name).distinct().all()
    # for name_tuple in distinct_api_names:
    #     name = name_tuple[0]
    #     calls_by_api_name_simple[name] = {
    #         'total': APILog.query.filter_by(api_name=name).count(),
    #         'successful': APILog.query.filter_by(api_name=name, success=True).count(),
    #         'failed': APILog.query.filter_by(api_name=name, success=False).count()
    #     }

    stats = {
        "total_calls": total_calls,
        "successful_calls": successful_calls,
        "failed_calls": failed_calls,
        "calls_by_api_name": calls_by_api_name  # Hoặc calls_by_api_name_simple
    }

    return render_template('admin/api_logs.html',
                           user_info=admin_user_info,
                           logs=logs,
                           stats=stats)


@app.route('/my-lists/<int:list_id_to_delete>/delete', methods=['POST'])
# @login_required # Nếu bạn đã có decorator login_required, hãy dùng nó
def delete_my_vocabulary_list(list_id_to_delete):
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:
        flash("Vui lòng đăng nhập để thực hiện hành động này.", "warning")
        return redirect(url_for('home'))  # Hoặc trang login

    list_to_delete = VocabularyList.query.get(list_id_to_delete)

    if not list_to_delete:
        flash("Không tìm thấy danh sách để xóa.", "danger")
        return redirect(url_for('my_lists_page'))

    # QUAN TRỌNG: Kiểm tra xem danh sách có thực sự thuộc về người dùng hiện tại không
    if list_to_delete.user_id != current_user_db_id:
        flash("Bạn không có quyền xóa danh sách này.", "danger")
        return redirect(url_for('my_lists_page'))

    try:
        list_name_deleted = list_to_delete.name
        db.session.delete(list_to_delete)
        db.session.commit()
        flash(f"Đã xóa thành công danh sách '{list_name_deleted}'.", "success")
        print(
            f"User {current_user_db_id} đã xóa list ID {list_id_to_delete} ('{list_name_deleted}') của chính họ.")  # Debug
    except Exception as e:
        db.session.rollback()
        flash(f"Có lỗi xảy ra khi xóa danh sách: {str(e)}", "danger")
        print(f"Lỗi khi user {current_user_db_id} xóa list ID {list_id_to_delete}: {e}")  # Debug

    return redirect(url_for('my_lists_page'))


@app.route('/my-lists/entry/<int:entry_id>/delete', methods=['POST'])
# @login_required # Nếu bạn đã có decorator login_required, hãy dùng nó
def delete_my_vocab_entry(entry_id):
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:
        flash("Vui lòng đăng nhập để thực hiện hành động này.", "warning")
        return redirect(url_for('home'))  # Hoặc trang login

    entry_to_delete = VocabularyEntry.query.get(entry_id)

    if not entry_to_delete:
        flash("Không tìm thấy từ để xóa.", "danger")
        # Nếu không biết redirect về list nào, có thể về trang my_lists chung
        return redirect(request.referrer or url_for('my_lists_page'))

    # QUAN TRỌNG: Kiểm tra xem entry này có thuộc về người dùng hiện tại không
    # Cách 1: Qua user_id trực tiếp trên VocabularyEntry
    # if entry_to_delete.user_id != current_user_db_id:
    # Cách 2 (An toàn hơn nếu user_id trên entry có thể không đồng bộ với list owner): Qua list cha
    if entry_to_delete.vocabulary_list.user_id != current_user_db_id:
        flash("Bạn không có quyền xóa từ này.", "danger")
        return redirect(url_for('list_detail_page', list_id=entry_to_delete.list_id))

    parent_list_id = entry_to_delete.list_id  # Lấy list_id để redirect lại
    entry_original_word = entry_to_delete.original_word

    try:
        db.session.delete(entry_to_delete)
        db.session.commit()
        flash(f"Đã xóa thành công từ '{entry_original_word}' khỏi danh sách.", "success")
        print(
            f"User {current_user_db_id} đã xóa entry ID {entry_id} ('{entry_original_word}') khỏi list ID {parent_list_id}")  # Debug
    except Exception as e:
        db.session.rollback()
        flash(f"Có lỗi xảy ra khi xóa từ: {str(e)}", "danger")
        print(f"Lỗi khi user {current_user_db_id} xóa entry ID {entry_id}: {e}")  # Debug

    return redirect(url_for('list_detail_page', list_id=parent_list_id))


@app.route('/my-lists/entry/<int:entry_id>/edit', methods=['POST'])
# @login_required # Nếu bạn đã có decorator login_required
def edit_my_vocab_entry(entry_id):
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:
        return jsonify({"success": False, "message": "Vui lòng đăng nhập."}), 401

    entry_to_edit = VocabularyEntry.query.get(entry_id)

    if not entry_to_edit:
        return jsonify({"success": False, "message": "Không tìm thấy mục từ vựng."}), 404

    # QUAN TRỌNG: Kiểm tra xem entry này có thuộc về người dùng hiện tại không
    if entry_to_edit.user_id != current_user_db_id:
        return jsonify({"success": False, "message": "Bạn không có quyền sửa mục từ vựng này."}), 403

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Không có dữ liệu được gửi."}), 400

    try:
        # Cập nhật các trường có thể sửa đổi
        # original_word không cho sửa qua form này
        entry_to_edit.word_type = data.get('word_type', entry_to_edit.word_type)
        entry_to_edit.definition_en = data.get('definition_en', entry_to_edit.definition_en)
        entry_to_edit.definition_vi = data.get('definition_vi', entry_to_edit.definition_vi)
        entry_to_edit.example_en = data.get('example_en', entry_to_edit.example_en)
        # Có thể thêm trường cập nhật thời gian sửa đổi nếu muốn
        # entry_to_edit.updated_at = datetime.utcnow()

        db.session.commit()
        flash(f"Đã cập nhật thành công mục từ '{entry_to_edit.original_word}'.", "success")  # Sẽ hiển thị khi reload
        print(f"User {current_user_db_id} đã sửa entry ID {entry_id} ('{entry_to_edit.original_word}')")  # Debug
        return jsonify({"success": True, "message": "Cập nhật thành công!"})

    except Exception as e:
        db.session.rollback()
        print(f"Lỗi khi User {current_user_db_id} sửa entry ID {entry_id}: {e}")
        return jsonify({"success": False, "message": f"Lỗi server: {str(e)}"}), 500


if __name__ == '__main__':
    with app.app_context():
        app.run(debug=True)
