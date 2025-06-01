# app.py
import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_dance.contrib.google import make_google_blueprint, google
from flask_sqlalchemy import SQLAlchemy  # <<< THÊM DÒNG NÀY
from sqlalchemy import func
from sqlalchemy.sql import case
from dotenv import load_dotenv  # Thêm dòng này
from flask_wtf.csrf import CSRFProtect
from flask_wtf import FlaskForm

from wtforms import TextAreaField, HiddenField, SubmitField, StringField, PasswordField, BooleanField

from wtforms.validators import DataRequired, Email, EqualTo, Length

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
app.secret_key = os.environ.get("FLASK_SECRET_KEY",
                                "a_default_fallback_secret_key_if_not_set_for_dev")  # Nên có fallback cho dev

# --- Cấu hình SQLAlchemy ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///vocabulary_app.db'  # <<< THÊM: Đường dẫn tới file database SQLite
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # <<< THÊM: Tắt thông báo không cần thiết

db.init_app(app)
migrate = Migrate(app, db)

csrf = CSRFProtect(app)  # Khởi tạo CSRFProtect

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


class RegistrationForm(FlaskForm):
    name = StringField('Họ và Tên', validators=[DataRequired()])
    email = StringField('Địa chỉ Email', validators=[DataRequired(), Email()])
    password = PasswordField('Mật khẩu', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Xác nhận Mật khẩu',
                                     validators=[DataRequired(),
                                                 EqualTo('password', message='Mật khẩu xác nhận không khớp.')])
    agree_terms = BooleanField(
        'Tôi đã đọc và đồng ý với các <a href="..." target="_blank">Điều khoản Dịch vụ</a> và <a href="..." target="_blank">Chính sách Bảo mật</a>.',
        validators=[DataRequired(message="Bạn phải đồng ý với các điều khoản.")])
    submit = SubmitField('Đăng ký')


def get_current_user_info():
    db_user_id = session.get("db_user_id")
    if db_user_id:
        user_from_db = User.query.get(db_user_id)  # User model đã được import từ models.py
        if user_from_db:
            return {
                "name": user_from_db.name,
                "email": user_from_db.email,
                "display_name": user_from_db.display_name,
                "picture": user_from_db.picture_url,
                "is_admin": user_from_db.is_admin  # <<< ĐẢM BẢO CÓ DÒNG NÀY
            }
    # Xử lý trường hợp đăng nhập bằng Google mà chưa có db_user_id trong session (lần đầu)
    if google.authorized:
        user_info_google = session.get("user_info")
        if user_info_google:
            user_info_google['is_admin'] = False  # Mặc định
            user_info_google['display_name'] = user_info_google.get('name')  # Tạm đặt bằng name
            user_info_google['google_id'] = user_info_google.get('id') or user_info_google.get('sub')
            return user_info_google
    return None


app.register_blueprint(google_bp, url_prefix="/login")


# --- Các Route của ứng dụng ---
@app.route('/')
def home():
    # if session.get("db_user_id"):
    #     return redirect(url_for('dashboard_page'))
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
                        display_user_info = get_current_user_info()  # Cập nhật lại
                        flash('Đăng nhập bằng Google thành công!', 'success')  # Có thể thêm flash
                        return redirect(url_for('home'))
            else:  # Không lấy được google_id hoặc email từ Google
                flash("Không thể xác thực với Google, thiếu thông tin định danh.", "danger")
                return redirect(url_for('logout'))

    # Hiển thị trang chủ
    return render_template('index.html', user_info=display_user_info)


@app.route('/auth/google/complete-setup', methods=['GET', 'POST'])
def google_complete_setup_page():
    pending_google_user = session.get('google_auth_pending_setup')
    if not pending_google_user:
        flash("Không có thông tin để hoàn tất đăng ký Google, hoặc phiên đã hết hạn.", "warning")
        return redirect(url_for('home'))

    current_display_user_info = get_current_user_info()

    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        agree_terms = request.form.get('agree_terms') == 'on'

        error_occurred = False
        if not password or not confirm_password:
            flash("Vui lòng nhập mật khẩu và xác nhận mật khẩu.", "danger")
            error_occurred = True
        elif len(password) < 6:
            flash("Mật khẩu phải có ít nhất 6 ký tự.", "danger")
            error_occurred = True
        elif password != confirm_password:
            flash("Mật khẩu và xác nhận mật khẩu không khớp.", "danger")
            error_occurred = True
        elif not agree_terms:
            flash("Bạn phải đồng ý với các điều khoản và điều kiện để tiếp tục.", "danger")
            error_occurred = True

        if error_occurred:
            return redirect(url_for('google_complete_setup_page'))  # PRG: Redirect về GET để hiển thị lỗi

        # Nếu không có lỗi validation, tiếp tục xử lý
        google_id = pending_google_user['google_id']
        email = pending_google_user['email']
        name = pending_google_user.get('name')
        picture = pending_google_user.get('picture')

        user = User.query.filter_by(google_id=google_id).first()
        if not user:
            user = User.query.filter_by(email=email).first()

        try:
            if user:
                user.google_id = google_id
                user.set_password(password)
                # Quyết định cách cập nhật name và picture:
                # Cách 1: Ưu tiên thông tin từ Google nếu user chưa có
                user.name = user.name or name
                user.picture_url = user.picture_url or picture
                # Cách 2: Luôn cập nhật từ Google (nếu Google cung cấp)
                # if name: user.name = name
                # if picture: user.picture_url = picture
            else:
                user = User(
                    google_id=google_id, email=email, name=name, picture_url=picture,
                    is_admin=False, is_blocked=False
                )
                user.set_password(password)
                db.session.add(user)

            db.session.commit()

            session.pop('google_auth_pending_setup', None)
            session['db_user_id'] = user.id
            session['user_info'] = {
                'name': user.name, 'display_name': user.display_name,  # Thêm display_name nếu có
                'email': user.email, 'picture': user.picture_url,
                'is_admin': user.is_admin
            }
            flash('Hoàn tất đăng ký và đăng nhập thành công!', 'success')
            return redirect(url_for('home'))  # Đã đổi thành home theo yêu cầu trước
        except Exception as e:
            db.session.rollback()
            flash(f"Có lỗi xảy ra khi lưu thông tin: {str(e)}", "danger")
            print(f"Lỗi khi hoàn tất đăng ký Google cho {email}: {e}")
            return redirect(url_for('google_complete_setup_page'))  # PRG: Redirect về GET nếu có lỗi DB

    # Cho GET request
    return render_template('auth/google_complete_setup.html',
                           user_info=current_display_user_info,
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
    print(f"--- Request to /login ---")  # DEBUG
    print(f"Method: {request.method}")  # DEBUG
    print(f"Is JSON: {request.is_json}")  # DEBUG
    if request.is_json:
        print(
            f"Request JSON data: {request.get_json(silent=True)}")  # DEBUG, silent=True để không crash nếu không phải JSON
    else:
        print(f"Request Form data: {request.form}")  # DEBUG
        print(f"Request Headers: {request.headers}")  # DEBUG
    if request.method == 'GET':
        if session.get("db_user_id") or google.authorized:
            return redirect(url_for('home'))
        # Nếu chưa đăng nhập và vào /login bằng GET, bạn có thể muốn mở modal trên trang chủ
        # hoặc nếu bạn có trang login.html riêng biệt thì render nó.
        # Hiện tại, chúng ta ưu tiên modal trên trang chủ.
        return redirect(url_for('home', open_login_modal='true'))

        # Xử lý POST request (thường là từ AJAX của login modal)
    if request.method == 'POST':
        # Kiểm tra xem có phải là AJAX request không (client nên gửi Content-Type: application/json)
        if not request.is_json:
            print("ERROR: Request POST to /login is not JSON")  # DEBUG
            # Nếu không phải JSON (ví dụ form HTML submit truyền thống đến đây),
            # có thể xử lý khác hoặc báo lỗi.
            # Hiện tại, chúng ta chỉ mong đợi JSON từ modal.
            return jsonify({"success": False,
                            "message": "Yêu cầu không hợp lệ. Dữ liệu phải là JSON."}), 415  # Unsupported Media Type

        data = request.get_json()
        if not data:
            print("ERROR: No JSON data received in POST to /login")  # DEBUG
            return jsonify({"success": False, "message": "Không nhận được dữ liệu."}), 400  # Bad Request

        email = data.get('email')
        password = data.get('password')
        print(f"Login attempt for email: {email}")  # DEBUG

        if not email or not password:
            return jsonify({"success": False, "message": "Vui lòng nhập đầy đủ email và mật khẩu."}), 400

        user = User.query.filter_by(email=email).first()

        if user and user.password_hash and user.check_password(password):
            if user.is_blocked:
                print(f"Login FAILED for {email}: Account blocked")  # DEBUG
                return jsonify({"success": False,
                                "message": "Tài khoản của bạn đã bị khóa. Vui lòng liên hệ quản trị viên."}), 403  # Forbidden

            session.clear()
            session['db_user_id'] = user.id
            # Tạo user_info cho session từ DB, đảm bảo get_current_user_info() sẽ có is_admin
            actual_user_info = {
                'name': user.name,
                'display_name': user.display_name,
                'email': user.email,
                'picture': user.picture_url,
                'is_admin': user.is_admin
            }
            session['user_info'] = actual_user_info
            print(f"Login SUCCESS for {email}")  # DEBUG

            print(f"User {user.email} đăng nhập bằng form thành công.")  # Debug
            return jsonify({"success": True, "message": "Đăng nhập thành công!"})  # Status 200 (mặc định)
        else:
            print(f"Đăng nhập thất bại cho email: {email}")  # Debug
            print(f"Login FAILED for {email}: Invalid credentials or no password_hash")  # DEBUG
            return jsonify({"success": False, "message": "Email hoặc mật khẩu không đúng."}), 401  # Unauthorized

    # Trường hợp khác (không phải GET cũng không phải POST hợp lệ)
    return jsonify({"success": False, "message": "Phương thức không được hỗ trợ."}), 405  # Method Not Allowed


# --- Route Đăng ký ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if session.get("db_user_id") or google.authorized:
        return redirect(url_for('home'))

    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        agree_terms = request.form.get('agree_terms')  # <<< LẤY GIÁ TRỊ CHECKBOX

        # Kiểm tra các trường input
        if not name or not email or not password or not confirm_password:
            flash('Vui lòng điền đầy đủ thông tin.', 'danger')
            return redirect(url_for('register'))

        if len(password) < 6:
            flash("Mật khẩu phải có ít nhất 6 ký tự.", "danger")
            return redirect(url_for('register'))

        if password != confirm_password:
            flash('Mật khẩu và xác nhận mật khẩu không khớp.', 'danger')
            return redirect(url_for('register'))

        # KIỂM TRA AGREE_TERMS Ở ĐÂY
        if not agree_terms:  # Checkbox nếu không được chọn sẽ không gửi giá trị, nên request.form.get sẽ là None
            flash('Bạn phải đồng ý với Điều khoản Dịch vụ và Chính sách Bảo mật để đăng ký.', 'danger')
            return redirect(url_for('register'))

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Địa chỉ email này đã được sử dụng.', 'warning')
            return redirect(url_for('register'))

        new_user = User(name=name, email=email)
        new_user.set_password(password)

        try:
            db.session.add(new_user)
            db.session.commit()
            # Có thể thêm một trường is_terms_agreed vào model User nếu bạn muốn lưu trạng thái này
            flash('Đăng ký thành công! Vui lòng đăng nhập.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            flash(f'Đã xảy ra lỗi khi đăng ký: {str(e)}', 'danger')
            print(f"Error during registration: {e}")
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
    # Sẽ trả về một danh sách CHỈ chứa MỘT dictionary nếu tìm thấy định nghĩa phù hợp
    # Hoặc danh sách rỗng nếu không.

    api_name = "dictionary_api"
    user_id_to_log = session.get("db_user_id")
    log_entry = APILog(api_name=api_name, request_details=f"Word: {word}", user_id=user_id_to_log, success=False)

    try:
        response = requests.get(DICTIONARY_API_URL, timeout=15)
        log_entry.status_code = response.status_code
        response.raise_for_status()
        data = response.json()

        # print(f"DEBUG: Dictionary API response for '{word}': {data}")

        if isinstance(data, list) and len(data) > 0:
            first_entry_data = data[0]  # Thường API này trả về một mảng với một phần tử chính cho từ đó

            ipa_text = "N/A"
            if first_entry_data.get("phonetics"):
                for phonetic_item in first_entry_data["phonetics"]:
                    if phonetic_item.get("text"):  # Ưu tiên lấy IPA text
                        ipa_text = phonetic_item.get("text")
                        break  # Lấy IPA đầu tiên tìm thấy

            # Tìm định nghĩa đầu tiên có nội dung và ưu tiên có ví dụ
            if first_entry_data.get("meanings"):
                for meaning_obj in first_entry_data["meanings"]:
                    part_of_speech = meaning_obj.get("partOfSpeech", "N/A")
                    if meaning_obj.get("definitions"):
                        # Ưu tiên định nghĩa có ví dụ trước
                        definition_with_example = None
                        first_definition_without_example = None

                        for definition_obj_item in meaning_obj["definitions"]:
                            definition_en = definition_obj_item.get("definition")
                            example_en = definition_obj_item.get("example")

                            if definition_en:
                                current_details = {
                                    "type": part_of_speech,
                                    "definition_en": definition_en,
                                    "example_en": example_en if example_en else "N/A",
                                    "ipa": ipa_text  # Thêm IPA vào đây
                                }
                                if example_en:  # Nếu định nghĩa này có ví dụ, chọn nó luôn
                                    log_entry.success = True
                                    return [current_details]
                                if not first_definition_without_example:  # Lưu lại định nghĩa đầu tiên (kể cả không có ví dụ)
                                    first_definition_without_example = current_details

                        # Nếu không có định nghĩa nào có ví dụ, dùng định nghĩa đầu tiên tìm được
                        if first_definition_without_example:
                            log_entry.success = True
                            return [first_definition_without_example]

            # Nếu không tìm thấy định nghĩa nào trong meanings nhưng có IPA
            if ipa_text != "N/A":
                log_entry.success = True  # Coi như thành công nếu lấy được IPA
                return [{"type": "N/A", "definition_en": "No definition found.", "example_en": "N/A", "ipa": ipa_text}]

            log_entry.error_message = "No valid definitions or IPA found."
            print(f"No definitions or IPA found for '{word}'.")
        else:
            log_entry.error_message = "No detailed entry found or unexpected format from API."
            print(f"No detailed entry found or unexpected format for '{word}'.")

    # ... (phần except và finally giữ nguyên để ghi log) ...
    except requests.exceptions.Timeout as e:
        log_entry.error_message = f"Timeout: {str(e)}"
        # ...
    except requests.exceptions.HTTPError as http_err:
        log_entry.error_message = f"HTTP Error: {str(http_err)}"
        # ...
    except Exception as e:
        log_entry.error_message = f"Unexpected Error: {str(e)}"
        # ...
    finally:
        db.session.add(log_entry)
        db.session.commit()

    return []  # Trả về danh sách rỗng nếu không thành công


# File: app.py
# ... (các import và hàm translate_with_deep_translator (phiên bản dịch đơn lẻ) của bạn) ...

# File: app.py

@app.route('/enter-words', methods=['GET', 'POST'])
def enter_words_page():
    form = GenerateWordsForm()  # Khởi tạo form
    display_user_info = get_current_user_info()
    user_lists = []
    target_list_info = None
    current_user_db_id = session.get("db_user_id")

    if display_user_info and current_user_db_id:
        user_lists = VocabularyList.query.filter_by(user_id=current_user_db_id).order_by(
            VocabularyList.name.asc()).all()

    # Xử lý target_list_info cho GET request (giữ nguyên logic của bạn)
    if request.method == 'GET':
        target_list_id_from_url = request.args.get('target_list_id', type=int)
        if target_list_id_from_url and current_user_db_id:
            list_obj = VocabularyList.query.filter_by(id=target_list_id_from_url, user_id=current_user_db_id).first()
            if list_obj:
                target_list_info = {"id": list_obj.id, "name": list_obj.name}
                flash(f"Bạn đang thêm từ vào danh sách: '{list_obj.name}'. Các từ sẽ được lưu vào danh sách này.",
                      "info")
                # Truyền target_list_id vào hidden field của form cho lần POST sau
                form.target_list_id_on_post.data = list_obj.id
            else:
                flash("Không tìm thấy danh sách được chỉ định hoặc bạn không có quyền.", "warning")
                return redirect(url_for('my_lists_page'))

    input_str = ""  # Sẽ được lấy từ form nếu POST thành công
    processed_results_dict = {}

    # Sử dụng form.validate_on_submit() cho POST request
    if form.validate_on_submit():  # Tự động xử lý CSRF và validators
        input_str = form.words_input.data
        session['last_processed_input'] = input_str  # Vẫn lưu session để có thể dùng nếu cần

        # Lấy lại target_list_id từ hidden field của form nếu có
        target_list_id_from_form = form.target_list_id_on_post.data
        if target_list_id_from_form and current_user_db_id:
            list_obj = VocabularyList.query.filter_by(id=target_list_id_from_form, user_id=current_user_db_id).first()
            if list_obj:
                target_list_info = {"id": list_obj.id, "name": list_obj.name}
        elif target_list_info:  # Giữ lại target_list_info từ GET nếu không có từ form (trường hợp hiếm)
            form.target_list_id_on_post.data = target_list_info.get('id')

        words_list = [word.strip() for word in input_str.split(',') if word.strip()]

        if words_list:
            # (Toàn bộ logic gọi API từ điển, dịch, và xây dựng processed_results_dict của bạn giữ nguyên ở đây)
            # ...
            for original_word in words_list:
                # ... (logic của bạn) ...
                detailed_entries = get_word_details_dictionaryapi(original_word)
                processed_results_dict[original_word] = []
                if detailed_entries:
                    entry_detail = detailed_entries[0]
                    english_definition = entry_detail["definition_en"]
                    vietnamese_explanation = "Không thể dịch giải thích này."
                    if english_definition and english_definition.strip() and english_definition.lower() != "n/a":
                        if english_definition.lower() != original_word.lower():
                            translated_definition = translate_with_deep_translator(english_definition)
                            if translated_definition and translated_definition.strip().lower() != english_definition.strip().lower():
                                vietnamese_explanation = translated_definition
                        else:
                            translated_word_meaning = translate_with_deep_translator(original_word)
                            if translated_word_meaning and translated_word_meaning.strip().lower() != original_word.strip().lower():
                                vietnamese_explanation = translated_word_meaning

                    processed_results_dict[original_word].append({
                        "type": entry_detail["type"], "definition_en": english_definition,
                        "definition_vi": vietnamese_explanation, "example_sentence": entry_detail["example_en"],
                        "ipa": entry_detail.get("ipa", "N/A")
                    })
                else:
                    vietnamese_translation_of_word = translate_with_deep_translator(original_word)
                    processed_results_dict[original_word].append({
                        "type": "N/A", "definition_en": original_word,
                        "definition_vi": vietnamese_translation_of_word if (
                                vietnamese_translation_of_word and vietnamese_translation_of_word.strip().lower() != original_word.strip().lower()) else "Không thể dịch từ này.",
                        "example_sentence": "N/A", "ipa": "N/A"
                    })
        elif input_str:
            flash("Vui lòng nhập từ hợp lệ.", "info")
            # Không cần redirect ở đây nếu form.validate_on_submit() xử lý lỗi validation
            # Nếu DataRequired của words_input báo lỗi, nó sẽ tự hiển thị lỗi trên form

    # Nếu là GET request, và không có input từ session (trang mới hoàn toàn)
    # hoặc nếu form POST không validate được, lấy lại giá trị input (nếu có) để điền lại form
    if request.method == 'GET':
        form.words_input.data = session.pop('last_processed_input', '')
        if not target_list_info:  # Chỉ xóa target_list_id khỏi session nếu không phải là target list mode
            session.pop('target_list_id_for_enter_words', None)  # Không cần thiết nếu dùng hidden field

    return render_template('enter_words.html',
                           form=form,  # <<< TRUYỀN FORM VÀO TEMPLATE
                           user_info=display_user_info,
                           input_words_str=form.words_input.data,  # Lấy từ form để giữ giá trị
                           results=processed_results_dict,
                           user_existing_lists=user_lists,
                           target_list_info=target_list_info)


# File: app.py
# ... (các import flask, session, flash, jsonify, models User, VocabularyList, VocabularyEntry, db, ...) ...

@app.route('/save-list', methods=['POST'])
# @login_required # Nếu bạn đã có decorator này
def save_list_route():
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:
        return jsonify({"success": False, "message": "Vui lòng đăng nhập."}), 401

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Không nhận được dữ liệu."}), 400

    vocabulary_items_data = data.get('words')
    list_name_from_input = data.get('list_name')
    existing_list_id = data.get('existing_list_id')

    if not vocabulary_items_data or not isinstance(vocabulary_items_data, list) or len(vocabulary_items_data) == 0:
        return jsonify({"success": False, "message": "Không có từ vựng nào để lưu."}), 400

    target_list = None
    is_new_list = False

    if existing_list_id:
        # Người dùng muốn thêm vào list đã có
        target_list = VocabularyList.query.filter_by(id=existing_list_id, user_id=current_user_db_id).first()
        if not target_list:
            return jsonify(
                {"success": False, "message": "Không tìm thấy danh sách hiện có hoặc bạn không có quyền."}), 403
    elif list_name_from_input and list_name_from_input.strip():
        # Người dùng muốn tạo list mới
        # Kiểm tra xem tên list mới có bị trùng không (cho cùng một user)
        existing_list_with_same_name = VocabularyList.query.filter_by(user_id=current_user_db_id,
                                                                      name=list_name_from_input.strip()).first()
        if existing_list_with_same_name:
            return jsonify({"success": False,
                            "message": f"Bạn đã có một danh sách với tên '{list_name_from_input.strip()}'. Vui lòng chọn tên khác."}), 400

        target_list = VocabularyList(name=list_name_from_input.strip(), user_id=current_user_db_id)
        db.session.add(target_list)
        is_new_list = True
        # ID sẽ được gán sau khi commit hoặc flush
    else:
        return jsonify({"success": False,
                        "message": "Vui lòng cung cấp tên cho danh sách mới hoặc chọn một danh sách hiện có."}), 400

    try:
        # Nếu là list mới, chúng ta cần flush để lấy ID trước khi thêm entry nếu entry cần list_id ngay.
        # Tuy nhiên, vì chúng ta gán `vocabulary_list=target_list`, SQLAlchemy sẽ xử lý quan hệ.
        # db.session.flush() # Có thể không cần thiết nếu dùng backref đúng cách

        for item_data in vocabulary_items_data:
            new_entry = VocabularyEntry(
                original_word=item_data.get('original_word'),
                word_type=item_data.get('word_type'),
                definition_en=item_data.get('definition_en'),
                definition_vi=item_data.get('definition_vi'),
                ipa=item_data.get('ipa'),  # Đảm bảo bạn đã thêm 'ipa' vào payload từ JS
                example_en=item_data.get('example_en'),
                user_id=current_user_db_id,
                vocabulary_list=target_list
            )
            db.session.add(new_entry)

        db.session.commit()  # Commit một lần ở cuối

        # Sau khi commit, target_list (nếu là mới) sẽ có ID
        final_list_id = target_list.id

        action_message = f"Đã thêm từ vào danh sách '{target_list.name}'." if existing_list_id else f"Đã tạo và lưu danh sách '{target_list.name}'."

        return jsonify({
            "success": True,
            "message": action_message,
            "list_id": final_list_id,  # Luôn trả về ID của list đã được sử dụng/tạo
            "is_new_list": is_new_list
        })

    except Exception as e:
        db.session.rollback()
        print(f"Lỗi khi lưu danh sách/từ: {e}")
        # Trả về thông báo lỗi cụ thể hơn nếu có thể (ví dụ: lỗi unique constraint)
        if "UNIQUE constraint failed" in str(e):
            return jsonify({"success": False,
                            "message": "Có lỗi xảy ra, có thể do tên danh sách đã tồn tại hoặc dữ liệu không hợp lệ."}), 400
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


class GenerateWordsForm(FlaskForm):
    words_input = TextAreaField('Enter Words here:', validators=[DataRequired()])
    target_list_id_on_post = HiddenField()
    submit = SubmitField('Generate')


def calculate_time_difference(start_date):
    if not start_date:
        return "N/A"
    now = datetime.utcnow()
    delta = now - start_date

    years = delta.days // 365
    remaining_days = delta.days % 365
    months = remaining_days // 30
    days = remaining_days % 30

    parts = []
    if years > 0:
        parts.append(f"{years} year{'s' if years > 1 else ''}")
    if months > 0:
        parts.append(f"{months} month{'s' if months > 1 else ''}")
    if days > 0 or (not years and not months):  # Show days if no years/months or if there are leftover days
        parts.append(f"{days} day{'s' if days > 1 else ''}")

    if not parts:  # Should not happen if start_date is valid
        return "Just joined!"
    return ", ".join(parts) + " ago"


@app.route('/profile', methods=['GET', 'POST'])
def profile_page():
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:
        flash("Vui lòng đăng nhập để xem hồ sơ của bạn.", "warning")
        return redirect(url_for('home', open_login_modal='true'))  # Gợi ý mở modal login nếu chưa đăng nhập

    user = User.query.get(current_user_db_id)
    if not user:
        flash("Không tìm thấy thông tin người dùng.", "danger")
        session.clear()  # Xóa session hỏng
        return redirect(url_for('home'))

    if request.method == 'POST':
        # Xử lý POST request cho việc đổi/đặt mật khẩu từ modal (AJAX)
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "message": "Dữ liệu không hợp lệ hoặc thiếu."}), 400

        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')
        current_password_from_form = data.get('current_password')  # Sẽ là None nếu người dùng đang đặt mật khẩu mới

        error_message = None
        can_set_password = False

        if user.password_hash:  # Người dùng đang THAY ĐỔI mật khẩu hiện có
            if not current_password_from_form:
                error_message = "Vui lòng nhập mật khẩu hiện tại của bạn."
            elif not user.check_password(current_password_from_form):
                error_message = "Mật khẩu hiện tại không đúng."
            else:
                can_set_password = True
        else:  # Người dùng đang ĐẶT mật khẩu mới (ví dụ: sau khi login Google)
            can_set_password = True

        if can_set_password and not error_message:
            if not new_password or not confirm_password:
                error_message = "Vui lòng nhập mật khẩu mới và xác nhận mật khẩu."
            elif len(new_password) < 6:
                error_message = "Mật khẩu mới phải có ít nhất 6 ký tự."
            elif new_password != confirm_password:
                error_message = "Mật khẩu mới và xác nhận mật khẩu không khớp."
            else:
                try:
                    user.set_password(new_password)  # Hàm này sẽ hash mật khẩu
                    # Cập nhật cả display_name nếu nó được gửi từ một form khác trên cùng trang profile
                    # Tuy nhiên, chúng ta đã có route /profile/update-info riêng cho display_name
                    db.session.commit()

                    # Cập nhật lại thông tin trong session['user_info'] nếu cần, đặc biệt là 'has_password'
                    # (Mặc dù reload trang sau đó sẽ tự làm điều này qua get_current_user_info)
                    if 'user_info' in session and session['user_info'] is not None:
                        session['user_info']['has_password'] = True  # Giả sử user_info có key này
                        session.modified = True

                    # flash("Đã cập nhật mật khẩu thành công!", "success") # Flash sẽ hiển thị sau khi reload trang
                    print(f"User {user.email} đã cập nhật/đặt mật khẩu.")  # Debug
                    return jsonify({"success": True, "message": "Đã cập nhật/đặt mật khẩu thành công!"})
                except Exception as e:
                    db.session.rollback()
                    error_message = f"Có lỗi xảy ra khi cập nhật mật khẩu: {str(e)}"
                    print(f"Lỗi khi user {user.email} cập nhật mật khẩu: {e}")

        # Nếu có lỗi validation trong quá trình xử lý POST từ AJAX
        if error_message:
            return jsonify({"success": False, "message": error_message}), 400  # 400 Bad Request

    # Xử lý cho GET request (hiển thị trang profile)
    num_lists = VocabularyList.query.filter_by(user_id=user.id).count()
    num_entries = VocabularyEntry.query.filter_by(user_id=user.id).count()
    time_with_us_str = calculate_time_difference(user.created_at)

    user_profile_data = {
        "name": user.name,
        "display_name": user.display_name,
        "email": user.email,
        "picture": user.picture_url,
        "has_password": bool(user.password_hash),  # Quan trọng cho việc hiển thị form trong modal
        "google_id": user.google_id,
        "created_at": user.created_at,
        "time_with_us": time_with_us_str
    }

    user_dashboard_stats = {
        "num_lists": num_lists,
        "num_entries": num_entries
    }

    base_user_info = get_current_user_info()  # Lấy thông tin cho base.html

    return render_template('profile.html',
                           user_profile_info=user_profile_data,
                           user_stats=user_dashboard_stats,
                           user_info=base_user_info)


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


@app.route('/dashboard')
# @login_required  # Sử dụng decorator nếu bạn đã tạo, nếu không thì dùng logic session.get("db_user_id")
def dashboard_page():
    current_user_db_id = session.get("db_user_id")
    # Kiểm tra đăng nhập (nếu không dùng @login_required)
    if not current_user_db_id:
        flash("Vui lòng đăng nhập để truy cập dashboard.", "warning")
        return redirect(url_for('home', open_login_modal='true'))

    display_user_info = get_current_user_info()
    if not display_user_info:
        flash("Không thể tải thông tin người dùng.", "danger")
        return redirect(url_for('logout'))

    # Lấy các thống kê
    num_lists = VocabularyList.query.filter_by(user_id=current_user_db_id).count()
    num_entries = VocabularyEntry.query.filter_by(user_id=current_user_db_id).count()

    stats = {
        "num_lists": num_lists,
        "num_entries": num_entries
    }

    # Lấy một vài danh sách gần đây (ví dụ: 3 danh sách)
    recent_lists = VocabularyList.query.filter_by(user_id=current_user_db_id).order_by(
        VocabularyList.created_at.desc()).limit(3).all()

    # LẤY CÁC TỪ MỚI THÊM GẦN ĐÂY (ví dụ: 5 từ)
    recent_entries = VocabularyEntry.query.filter_by(user_id=current_user_db_id).order_by(
        VocabularyEntry.added_at.desc()).limit(5).all()

    print(
        f"Dashboard for user {current_user_db_id}: {stats}, {len(recent_lists)} recent lists, {len(recent_entries)} recent entries")  # Debug

    return render_template('dashboard.html',
                           user_info=display_user_info,
                           user_stats=stats,
                           recent_lists=recent_lists,
                           recent_entries=recent_entries)  # <<< THÊM recent_entries


@app.route('/profile/update-info', methods=['POST'])
# @login_required
def update_profile_info_route():
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:
        flash("Vui lòng đăng nhập.", "warning")
        return redirect(url_for('home'))

    user_to_update = User.query.get(current_user_db_id)
    if not user_to_update:
        flash("Lỗi: Không tìm thấy người dùng.", "danger")
        return redirect(url_for('home'))

    new_display_name = request.form.get('display_name', '').strip()

    if len(new_display_name) > 100:
        flash("Tên hiển thị quá dài (tối đa 100 ký tự).", "danger")
        return redirect(url_for('profile_page'))

    user_to_update.display_name = new_display_name if new_display_name else None
    try:
        db.session.commit()
        flash("Đã cập nhật thông tin hồ sơ thành công!", "success")
        if 'user_info' in session and session['user_info'] is not None:
            session['user_info']['name'] = new_display_name if new_display_name else user_to_update.name
            session['user_info']['display_name'] = new_display_name if new_display_name else None
            session.modified = True
    except Exception as e:
        db.session.rollback()
        flash(f"Lỗi khi cập nhật thông tin: {str(e)}", "danger")
    return redirect(url_for('profile_page'))


@app.route('/my-lists/<int:list_id_to_delete>/delete', methods=['POST'])
# @login_required  # Đảm bảo người dùng đã đăng nhập
def delete_my_list(list_id_to_delete):
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:  # Kiểm tra thêm nếu @login_required không đủ hoặc có lỗi
        flash("Please log in to manage your lists.", "warning")
        return redirect(url_for('login_page'))  # Hoặc home nếu bạn muốn họ ở lại trang chủ

    list_to_delete = VocabularyList.query.get_or_404(list_id_to_delete)

    # Kiểm tra quyền sở hữu
    if list_to_delete.user_id != current_user_db_id:
        flash("You do not have permission to delete this list.", "danger")
        return redirect(url_for('my_lists_page'))

    try:
        db.session.delete(list_to_delete)  # Cascade delete sẽ xóa các VocabularyEntry liên quan
        db.session.commit()
        flash(f"Vocabulary list '{list_to_delete.name}' and all its words have been deleted successfully.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"An error occurred while trying to delete the list: {str(e)}", "danger")
        print(f"Error deleting list {list_id_to_delete} for user {current_user_db_id}: {e}")

    return redirect(url_for('my_lists_page'))


@app.route('/my-lists/<int:list_id>/rename-ajax', methods=['POST'])  # Đổi tên route để rõ là AJAX
# @login_required
def rename_my_list_ajax(list_id):
    current_user_db_id = session.get("db_user_id")
    list_to_rename = VocabularyList.query.get_or_404(list_id)

    if list_to_rename.user_id != current_user_db_id:
        return jsonify({"success": False, "message": "You do not have permission to rename this list."}), 403

    data = request.get_json()
    if not data or 'new_list_name' not in data:
        return jsonify({"success": False, "message": "New list name not provided."}), 400

    new_name = data.get('new_list_name', '').strip()

    if not new_name:
        return jsonify({"success": False, "message": "List name cannot be empty."}), 400
    if len(new_name) > 100:  # Ví dụ giới hạn độ dài
        return jsonify({"success": False, "message": "List name is too long (max 100 characters)."}), 400

    # Kiểm tra xem tên mới có trùng với list khác của user không
    existing_list_with_new_name = VocabularyList.query.filter(
        VocabularyList.user_id == current_user_db_id,
        VocabularyList.name == new_name,
        VocabularyList.id != list_id  # Loại trừ list hiện tại
    ).first()

    if existing_list_with_new_name:
        return jsonify({"success": False, "message": f"A list with the name '{new_name}' already exists."}), 400

    try:
        list_to_rename.name = new_name
        db.session.commit()
        # Không cần flash ở đây vì AJAX sẽ xử lý hiển thị thông báo
        return jsonify({"success": True, "message": "List renamed successfully.", "new_name": new_name})
    except Exception as e:
        db.session.rollback()
        print(f"Error renaming list {list_id} for user {current_user_db_id}: {e}")
        return jsonify({"success": False, "message": "An error occurred while renaming the list."}), 500


if __name__ == '__main__':
    with app.app_context():
        app.run(debug=True)
