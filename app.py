# app.py

# --- Standard Library Imports ---
import os  # Để tương tác với hệ điều hành, ví dụ: đọc biến môi trường
from datetime import datetime, timedelta  # Để làm việc với ngày giờ, ví dụ: created_at, added_at
from functools import wraps  # Để tạo decorator (ví dụ: @login_required, @admin_required)

# --- Flask and Related Extensions ---
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import \
    SQLAlchemy  # Dòng này có thể không cần nếu db đã được khởi tạo trong models.py và chỉ import db từ đó
from flask_migrate import Migrate  # Cho việc quản lý thay đổi schema database
from flask_dance.contrib.google import make_google_blueprint, google  # Cho việc đăng nhập bằng Google OAuth
from flask_wtf import FlaskForm  # Lớp cơ sở để tạo form trong Flask-WTF
from flask_wtf.csrf import CSRFProtect  # Để bảo vệ chống lại tấn công CSRF
from sqlalchemy import func, case
from flask_wtf import FlaskForm

# --- WTForms Fields and Validators ---
from wtforms import StringField, PasswordField, BooleanField, TextAreaField, HiddenField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length  # Các validators cho trường dữ liệu form

# --- Third-Party Libraries ---
from dotenv import load_dotenv  # Để tải biến môi trường từ file .env
from deep_translator import GoogleTranslator  # Thư viện dịch thuật sử dụng Google Translate
import requests  # Để gửi các yêu cầu HTTP (ví dụ: gọi API)

# --- Application-Specific Imports ---
from models import db, User, VocabularyList, VocabularyEntry, \
    APILog, UserActivity  # Import SQLAlchemy instance (db) và các model từ file models.py

# === APPLICATION SETUP ===

# Tải các biến môi trường từ file .env (nếu có) vào os.environ
# Lệnh này nên được gọi sớm để các biến môi trường có sẵn khi cần
load_dotenv()

# Khởi tạo ứng dụng Flask
app = Flask(__name__)

app.config["GOOGLE_OAUTH_CLIENT_ID"] = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
app.config["GOOGLE_OAUTH_CLIENT_SECRET"] = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
app.secret_key = os.environ.get("FLASK_SECRET_KEY",
                                "a_default_fallback_secret_key_if_not_set_for_dev")  # Nên có fallback cho dev

# --- Cấu hình SQLAlchemy ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///vocabulary_app.db'  # Đường dẫn tới file database SQLite
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False  # Tắt thông báo không cần thiết

db.init_app(app)
migrate = Migrate(app, db)

csrf = CSRFProtect(app)  # Khởi tạo CSRFProtect

# --- Tạo Google Blueprint với Flask-Dance ---
google_bp = make_google_blueprint(
    client_id=app.config.get("GOOGLE_OAUTH_CLIENT_ID"),  # <<< Lấy từ app.config
    client_secret=app.config.get("GOOGLE_OAUTH_CLIENT_SECRET"),  # <<< Lấy từ app.config
    scope=[
        "openid",  # Quyền cơ bản để xác thực
        "https://www.googleapis.com/auth/userinfo.email",  # Quyền lấy địa chỉ email
        "https://www.googleapis.com/auth/userinfo.profile"  # Quyền lấy thông tin hồ sơ cơ bản (tên, ảnh)
    ],
    # redirect_url="/", # Tùy chọn: URL để chuyển hướng đến sau khi Google xác thực thành công
    # Mặc định Flask-Dance có thể tự xử lý, hoặc bạn có thể chỉ định một route cụ thể
    # Nếu bạn có route callback riêng, hãy đặt redirect_to="tên_endpoint_callback"
)

# Đăng ký Blueprint với ứng dụng Flask
app.register_blueprint(google_bp, url_prefix="/login")

# File: app.py (hoặc file chứa các helper/decorators của bạn)
from functools import wraps
from flask import session, flash, redirect, url_for
from models import User  # Đảm bảo User model đã được import


def login_required(f):
    """
    Decorator để kiểm tra xem người dùng hiện tại đã đăng nhập chưa.
    Nếu chưa, sẽ chuyển hướng họ về trang chủ và gợi ý mở modal đăng nhập.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("db_user_id"):
            flash("Please login to access this page.", "warning")
            return redirect(url_for('home', open_login_modal=True))
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    """
    Decorator để kiểm tra xem người dùng hiện tại có phải là Admin không.
    Nếu không phải Admin hoặc chưa đăng nhập, sẽ chuyển hướng họ.
    """

    @wraps(f)  # Giữ lại metadata của hàm gốc (f) như tên hàm, docstring
    def decorated_function(*args, **kwargs):
        # 1. Lấy ID người dùng từ session
        current_user_db_id = session.get("db_user_id")

        # 2. Kiểm tra xem người dùng đã đăng nhập chưa
        if not current_user_db_id:
            flash("Please login to access this page.", "warning")
            # Chuyển hướng về trang chủ và gợi ý mở modal đăng nhập
            # (JavaScript trên trang chủ có thể đọc param 'open_login_modal' để tự mở modal)
            return redirect(url_for('home', open_login_modal=True))

            # 3. Nếu đã đăng nhập, lấy thông tin người dùng từ database
        user = User.query.get(current_user_db_id)

        # 4. Kiểm tra xem người dùng có tồn tại và có phải là Admin không
        if not user or not user.is_admin:
            flash("You do not have permission to access the admin page.", "danger")
            # Chuyển hướng về trang chủ nếu không phải admin hoặc không tìm thấy user
            return redirect(url_for('home'))

        # 5. Nếu tất cả kiểm tra đều qua, cho phép thực thi hàm route gốc (f)
        return f(*args, **kwargs)

    return decorated_function


def get_current_user_info():
    """
    Lấy thông tin của người dùng hiện tại đang đăng nhập.
    Ưu tiên lấy thông tin từ database nếu người dùng đã được lưu và có session 'db_user_id'.
    Nếu không, thử lấy thông tin từ session của Google OAuth (trường hợp vừa xác thực qua Google).
    Trả về một dictionary chứa thông tin người dùng hoặc None nếu không có ai đăng nhập.
    """

    # 1. Ưu tiên kiểm tra session 'db_user_id' (người dùng đã đăng nhập vào hệ thống)
    db_user_id = session.get("db_user_id")

    if db_user_id:
        # Nếu có 'db_user_id' trong session, truy vấn database để lấy thông tin người dùng
        user_from_db = User.query.get(db_user_id)  # User model đã được import từ models.py

        if user_from_db:
            # Nếu tìm thấy người dùng trong database, trả về thông tin của họ
            # Bao gồm cả các trường tùy chỉnh như 'display_name' và 'is_admin'
            return {
                "name": user_from_db.name,  # Tên gốc (từ Google hoặc form đăng ký)
                "email": user_from_db.email,  # Email của người dùng
                "display_name": user_from_db.display_name,  # Tên hiển thị (nếu có)
                "picture": user_from_db.picture_url,  # URL ảnh đại diện
                "is_admin": user_from_db.is_admin,  # Trạng thái admin (True/False)
                # Bạn có thể thêm 'google_id': user_from_db.google_id nếu cần ở client
            }

    # 2. Nếu không có 'db_user_id' hoặc không tìm thấy user trong DB,
    #    kiểm tra xem người dùng có vừa xác thực qua Google không (Flask-Dance)
    if google.authorized:  # Kiểm tra xem session hiện tại có token OAuth hợp lệ của Google không
        # Flask-Dance thường lưu thông tin người dùng lấy từ Google vào session['user_info']
        # hoặc một key tương tự sau khi xác thực thành công.
        user_info_google = session.get("user_info")

        if user_info_google:
            # Nếu có thông tin từ Google trong session (thường là sau lần xác thực Google đầu tiên
            # trước khi tài khoản được tạo/liên kết hoàn toàn trong DB của bạn và có 'db_user_id')

            # Mặc định các giá trị cho ứng dụng của bạn:
            user_info_google['is_admin'] = False  # Người dùng mới từ Google mặc định không phải là admin
            user_info_google['display_name'] = user_info_google.get(
                'name')  # Tạm thời đặt display_name bằng tên từ Google

            # Lấy google_id (có thể là 'id' hoặc 'sub' tùy theo response của Google API)
            user_info_google['google_id'] = user_info_google.get('id') or user_info_google.get('sub')

            # Trả về thông tin lấy được từ Google, đã được bổ sung các trường mặc định
            # Thông tin này có thể được dùng để hiển thị tạm thời hoặc để hoàn tất quá trình đăng ký/liên kết tài khoản
            return user_info_google

    # 3. Nếu không có 'db_user_id' và cũng không có thông tin từ Google session hợp lệ,
    #    coi như không có người dùng nào đang đăng nhập.
    return None


@app.route('/')
def home():
    # Lấy thông tin người dùng hiện tại (nếu đã đăng nhập từ trước đó bằng form hoặc Google đã hoàn tất)
    display_user_info = get_current_user_info()

    # Xử lý callback sau khi Google OAuth xác thực thành công
    # Điều kiện này kiểm tra:
    # 1. google.authorized: Người dùng vừa xác thực thành công với Google (Flask-Dance đặt token vào session).
    # 2. not session.get("db_user_id"): Người dùng này CHƯA có session 'db_user_id' của hệ thống bạn,
    #    nghĩa là đây có thể là lần đầu họ đăng nhập bằng Google, hoặc họ vừa quay lại từ Google.
    if google.authorized and not session.get("db_user_id"):
        user_info_from_google = session.get("user_info")  # Flask-Dance thường lưu thông tin user Google vào đây

        if not user_info_from_google:  # Nếu vì lý do nào đó session['user_info'] chưa có, thử lấy lại từ API của Google
            try:
                resp = google.get("/oauth2/v2/userinfo")  # Gọi API Google UserInfo
                if resp.ok:
                    user_info_from_google = resp.json()
                    session["user_info"] = user_info_from_google  # Lưu lại vào session để dùng sau
                else:  # Không lấy được thông tin từ Google
                    flash("Could not get information from Google. Please try again.", "danger")
                    return redirect(url_for('logout'))  # Đăng xuất khỏi hệ thống và có thể cả Google Dance session
            except Exception as e:  # Lỗi mạng hoặc lỗi khác khi gọi API Google
                print(f"Error fetching user info from Google: {e}")
                flash("Error connecting to Google. Please try again.", "danger")
                return redirect(url_for('logout'))

        # Nếu đã có user_info_from_google (từ session hoặc vừa lấy được)
        if user_info_from_google:
            google_id = user_info_from_google.get("id") or user_info_from_google.get(
                "sub")  # Google ID có thể là 'id' hoặc 'sub'
            email = user_info_from_google.get("email")
            name_from_google = user_info_from_google.get("name")
            picture_from_google = user_info_from_google.get("picture")

            if google_id and email:  # Cần google_id và email để xử lý
                user = User.query.filter_by(google_id=google_id).first()  # Tìm user bằng google_id trước

                if not user:  # Nếu không tìm thấy user với google_id này
                    # Thử tìm user bằng email (có thể user này đã đăng ký bằng form trước đó)
                    user = User.query.filter_by(email=email).first()
                    if user:
                        # Tìm thấy user bằng email. Đây là trường hợp cần liên kết tài khoản Google này với user đã có.
                        if user.is_blocked:
                            flash('Your account (associated with this email) has been locked.', 'danger')
                            # Cần đảm bảo logout khỏi Google Dance session nếu có
                            token_key = f"{google_bp.name}_oauth_token"  # google_bp cần được định nghĩa và đăng ký trước đó
                            if token_key in session: del session[token_key]
                            return redirect(url_for('logout'))  # Ngăn đăng nhập

                        # Nếu user này chưa có google_id (chứng tỏ trước đó họ đăng ký bằng form), thì liên kết nó
                        if not user.google_id:
                            user.google_id = google_id
                            # Cập nhật thêm thông tin từ Google nếu muốn (name, picture),
                            # ưu tiên giữ lại thông tin cũ nếu đã có
                            user.name = user.name or name_from_google
                            user.picture_url = user.picture_url or picture_from_google
                            try:
                                db.session.commit()
                            except Exception as e:
                                db.session.rollback()
                                flash("Error linking Google account to existing account.", "danger")
                                return redirect(url_for('logout'))
                        # else: user này đã có google_id nhưng khác với google_id hiện tại (hiếm, có thể là lỗi logic hoặc user dùng nhiều tk Google cùng email)
                        #   Trong trường hợp này, có thể không làm gì hoặc báo lỗi. Hiện tại bạn đang bỏ qua.

                        # Sau khi liên kết, kiểm tra xem user này đã có mật khẩu hệ thống chưa
                        if not user.password_hash:
                            # Nếu chưa có mật khẩu, chuyển đến trang hoàn tất đăng ký để đặt mật khẩu
                            session['google_auth_pending_setup'] = {
                                'google_id': google_id, 'email': email,
                                'name': name_from_google, 'picture': picture_from_google
                            }
                            return redirect(url_for('google_complete_setup_page'))
                        else:
                            # User này đã có google_id (vừa liên kết hoặc đã có từ trước)
                            # VÀ đã có password_hash (đã hoàn tất setup) -> Đăng nhập thành công
                            session['db_user_id'] = user.id
                            display_user_info = get_current_user_info()  # Lấy lại thông tin đầy đủ từ DB
                            flash('Login with Google successful!', 'success')
                            return redirect(url_for('home'))  # Ở lại trang chủ

                    else:  # User hoàn toàn mới (không tìm thấy qua google_id, không tìm thấy qua email)
                        # Chuyển đến trang hoàn tất đăng ký để đặt mật khẩu
                        session['google_auth_pending_setup'] = {
                            'google_id': google_id, 'email': email,
                            'name': name_from_google, 'picture': picture_from_google
                        }
                        return redirect(url_for('google_complete_setup_page'))

                else:  # Đã tìm thấy user với google_id (đã đăng ký/liên kết Google trước đó)
                    if user.is_blocked:
                        flash('Your account has been locked.', 'danger')
                        token_key = f"{google_bp.name}_oauth_token"
                        if token_key in session: del session[token_key]
                        return redirect(url_for('logout'))

                    # Kiểm tra xem họ đã đặt mật khẩu hệ thống chưa
                    if not user.password_hash:
                        session['google_auth_pending_setup'] = {
                            'google_id': user.google_id, 'email': user.email,
                            'name': name_from_google or user.name,  # Ưu tiên tên từ Google nếu có, không thì tên cũ
                            'picture': picture_from_google or user.picture_url  # Tương tự cho ảnh
                        }
                        return redirect(url_for('google_complete_setup_page'))
                    else:
                        # User đã có google_id và password_hash -> đăng nhập thành công
                        session['db_user_id'] = user.id
                        display_user_info = get_current_user_info()  # Lấy lại thông tin đầy đủ
                        flash('Welcome back!', 'success')
                        return redirect(url_for('home'))  # Ở lại trang chủ
            else:
                flash("Unable to authenticate with Google, missing identifier (Google ID or Email).", "danger")
                return redirect(url_for('logout'))
        else:  # Không lấy được user_info_from_google
            flash("Unable to get profile information from Google after authentication.", "danger")
            return redirect(url_for('logout'))

    # Hiển thị trang chủ cho khách hoặc người dùng đã đăng nhập (không qua redirect)
    return render_template('index.html', user_info=display_user_info)


@app.route('/admin')  # Định nghĩa route cho trang admin, có thể truy cập qua /admin
@app.route('/admin/dashboard')  # Thêm một URL nữa cho dashboard nếu muốn, ví dụ /admin/dashboard
@admin_required  # Áp dụng decorator: Chỉ người dùng có quyền admin mới truy cập được route này
def admin_dashboard():
    """
    Hiển thị trang Admin Dashboard.
    Bao gồm danh sách tất cả người dùng và một số thông tin thống kê cơ bản của họ.
    """

    # 1. Lấy thông tin của Admin đang đăng nhập để truyền cho base template (ví dụ: hiển thị avatar ở header)
    admin_user_info = get_current_user_info()
    # Hàm get_current_user_info() cần trả về một dictionary chứa thông tin người dùng hiện tại,
    # bao gồm 'name', 'email', 'picture', 'is_admin', 'display_name'.

    # 2. Chuẩn bị danh sách dữ liệu người dùng để hiển thị trên "Learning Monitor"
    users_data = []  # Khởi tạo một danh sách rỗng để chứa thông tin của mỗi người dùng

    # Truy vấn tất cả người dùng từ database, sắp xếp theo ID tăng dần (hoặc tiêu chí khác nếu muốn)
    all_users_from_db = User.query.order_by(User.id.asc()).all()

    # Lặp qua từng đối tượng User lấy được từ database
    for user_item in all_users_from_db:
        # Với mỗi người dùng, tính toán số lượng danh sách từ vựng họ đã tạo
        num_lists = VocabularyList.query.filter_by(user_id=user_item.id).count()

        # Tính toán tổng số từ vựng (entries) mà người dùng này đã lưu trong tất cả các danh sách của họ
        num_entries = VocabularyEntry.query.filter_by(user_id=user_item.id).count()
        # Lưu ý: Điều này giả định model VocabularyEntry của bạn có trường user_id.
        # Nếu VocabularyEntry chỉ có list_id, bạn cần tính tổng số entry từ các list của user_item.

        # Thêm thông tin của người dùng hiện tại (user_item) và các thống kê vào danh sách users_data
        users_data.append({
            "id": user_item.id,  # ID của người dùng
            "name": user_item.name,  # Tên gốc (từ Google hoặc form đăng ký)
            "display_name": user_item.display_name,  # Tên hiển thị (nếu có)
            "username": user_item.email.split('@')[0],  # Tạo một "username" giả định từ phần trước @ của email
            "email": user_item.email,  # Email của người dùng
            "saved_words": num_entries,  # Số từ đã lưu
            "reviewed_words": 0,  # Placeholder: Số từ đã ôn tập (chưa có tính năng này)
            "progress": "Learning",  # Placeholder: Tiến độ học tập (chưa có tính năng này)
            "status_icon": "→",  # Placeholder: Icon trạng thái (có thể là link xem chi tiết)
            "is_admin": user_item.is_admin,  # Để biết người dùng này có phải là admin không
            "is_blocked": user_item.is_blocked  # Để biết người dùng này có bị chặn không
        })

    # 3. Render template cho Admin Dashboard và truyền dữ liệu vào
    # 'admin/admin_dashboard_main.html' là file template bạn đã tạo cho giao diện "Learning Monitor"
    # user_info: thông tin của Admin đang đăng nhập (cho base.html)
    # learning_monitor_users: danh sách dữ liệu người dùng đã được chuẩn bị ở trên
    return render_template('admin/admin_dashboard_main.html',
                           user_info=admin_user_info,
                           learning_monitor_users=users_data)


@app.route('/login-with-google')  # Định nghĩa route URL là /login-with-google
def login_with_google():
    """
    Route này dùng để khởi tạo quá trình đăng nhập bằng Google OAuth.
    Nó sẽ kiểm tra xem người dùng đã được Flask-Dance xác thực với Google chưa.
    Nếu chưa, nó sẽ chuyển hướng người dùng đến trang đăng nhập của Google.
    Nếu đã xác thực rồi (ví dụ, người dùng vừa quay lại từ Google), nó sẽ chuyển hướng về trang chủ.
    """

    # 1. Kiểm tra xem session hiện tại có token OAuth hợp lệ của Google không.
    #    google.authorized là một thuộc tính của đối tượng `google` (Flask-Dance blueprint)
    #    sẽ trả về True nếu có token hợp lệ trong session.
    if not google.authorized:
        # Nếu chưa được xác thực (chưa có token hoặc token không hợp lệ):
        # Chuyển hướng người dùng đến endpoint 'google.login' của Flask-Dance.
        # Flask-Dance sẽ tự động xử lý việc chuyển hướng người dùng đến trang đăng nhập của Google.
        return redirect(url_for("google.login"))
        # 'google.login' là endpoint mặc định mà Flask-Dance tạo ra trong google_bp
        # để bắt đầu luồng OAuth2.

    # 2. Nếu google.authorized là True:
    #    Điều này có nghĩa là người dùng đã hoàn thành việc xác thực với Google,
    #    và Flask-Dance đã lưu token vào session.
    #    Thông tin người dùng từ Google (profile, email) cũng có thể đã được lấy và lưu vào session['user_info']
    #    (tùy thuộc vào cấu hình của Flask-Dance hoặc nếu bạn đã gọi google.get(...) trước đó).
    #
    #    Chuyển hướng người dùng về trang chủ ('home').
    #    Route 'home' sẽ xử lý tiếp việc tạo/cập nhật user trong database,
    #    yêu cầu đặt mật khẩu nếu cần, và thiết lập session 'db_user_id' cho ứng dụng của bạn.
    return redirect(url_for("home"))


@app.route('/logout')  # Định nghĩa route URL là /logout
def logout():
    """
    Xử lý việc đăng xuất người dùng.
    Xóa các thông tin session liên quan đến Google OAuth (nếu có)
    và session của ứng dụng (thông tin người dùng đã đăng nhập vào hệ thống).
    Sau đó chuyển hướng về trang chủ.
    """

    # 1. Xóa token OAuth của Google khỏi session (nếu tồn tại)
    #    Flask-Dance lưu trữ token OAuth trong session với một key có dạng:
    #    <tên_blueprint>_oauth_token (ví dụ: 'google_oauth_token' nếu blueprint tên là 'google')
    #    google_bp.name sẽ trả về tên của blueprint Google mà bạn đã tạo (ví dụ: "google").
    token_key = f"{google_bp.name}_oauth_token"
    if token_key in session:
        del session[token_key]  # Xóa token khỏi session

    # 2. Xóa thông tin người dùng lấy từ Google (nếu có) khỏi session
    #    Đây là thông tin hồ sơ (profile, email) mà Flask-Dance hoặc code của bạn
    #    có thể đã lưu vào session['user_info'] sau khi xác thực Google.
    if "user_info" in session:
        del session["user_info"]

    # 3. Xóa thông tin định danh người dùng của ứng dụng bạn khỏi session
    #    session['db_user_id'] là key bạn dùng để lưu ID người dùng từ database của bạn,
    #    xác định rằng người dùng đã đăng nhập vào hệ thống của bạn.
    if "db_user_id" in session:
        del session["db_user_id"]

    # Bạn cũng có thể dùng session.clear() để xóa toàn bộ session,
    # nhưng cách xóa từng key cụ thể như trên sẽ an toàn hơn nếu bạn có
    # những thông tin khác trong session muốn giữ lại (ví dụ: ngôn ngữ, theme).
    # Nếu muốn xóa sạch, có thể dùng:
    # session.clear()

    # (Tùy chọn) Hiển thị một thông báo flash cho người dùng biết họ đã đăng xuất
    # flash("Bạn đã đăng xuất thành công.", "info")

    # 4. Chuyển hướng người dùng về trang chủ
    return redirect(url_for("home"))


@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    Xử lý yêu cầu đăng nhập của người dùng.
    - GET: Chuyển hướng người dùng nếu họ đã đăng nhập, hoặc hiển thị trang/modal đăng nhập.
    - POST: Xác thực thông tin đăng nhập, đặt session nếu thành công, và trả về JSON response.
    """

    # --- DEBUGGING: In thông tin request đến ---
    print(f"--- Request to /login ---")
    print(f"Method: {request.method}")
    print(f"Is JSON: {request.is_json}")  # Kiểm tra xem request có phải là JSON không
    if request.is_json:
        # In dữ liệu JSON nếu có (silent=True để không gây lỗi nếu không phải JSON hợp lệ)
        print(f"Request JSON data: {request.get_json(silent=True)}")
    else:
        # In dữ liệu form nếu không phải JSON (ví dụ: submit form HTML truyền thống)
        print(f"Request Form data: {request.form}")
        print(f"Request Headers: {request.headers}")  # In headers để kiểm tra Content-Type
    # --- KẾT THÚC DEBUGGING ---

    # --- Xử lý GET Request ---
    if request.method == 'GET':
        # Nếu người dùng đã đăng nhập (qua session 'db_user_id' hoặc Google session)
        if session.get("db_user_id") or google.authorized:
            return redirect(url_for('home'))  # Chuyển hướng về trang chủ

        # Nếu chưa đăng nhập và truy cập /login bằng GET:
        # Chuyển hướng về trang chủ và gợi ý mở modal đăng nhập bằng URL parameter.
        # JavaScript ở frontend có thể đọc 'open_login_modal' để tự động mở modal.
        return redirect(url_for('home', open_login_modal='true'))

    # --- Xử lý POST Request (thường từ AJAX của login modal) ---
    if request.method == 'POST':
        # 1. Kiểm tra Content-Type: Yêu cầu này có phải là JSON không?
        #    Login modal của chúng ta được thiết kế để gửi dữ liệu JSON.
        if not request.is_json:
            print("ERROR: Request POST to /login is not JSON")  # Debug
            # Trả về lỗi nếu client không gửi dữ liệu dưới dạng JSON như mong đợi
            return jsonify({"success": False,
                            "message": "Invalid request. Data must be JSON."}), 415  # 415 Unsupported Media Type

        # 2. Lấy dữ liệu JSON từ request
        data = request.get_json()
        if not data:  # Trường hợp get_json() trả về None (ví dụ: body rỗng dù content-type đúng)
            print("ERROR: No JSON data received in POST to /login")  # Debug
            return jsonify(
                {"success": False, "message": "Failed to receive JSON data from request."}), 400 # 400 Bad Request

        email = data.get('email')
        password = data.get('password')
        print(f"Login attempt for email: {email}")  # Debug

        # 3. Validate dữ liệu đầu vào (email và password)
        if not email or not password:
            return jsonify(
                {"success": False, "message": "Please enter full email and password."}), 400  # 400 Bad Request

        # 4. Tìm người dùng trong database bằng email
        user = User.query.filter_by(email=email).first()

        # 5. Xác thực người dùng:
        #    - User phải tồn tại.
        #    - User phải có password_hash (nghĩa là họ đã đăng ký bằng form hoặc đã đặt mật khẩu sau khi login Google).
        #    - Mật khẩu cung cấp phải khớp với password_hash đã lưu.
        if user and user.password_hash and user.check_password(password):
            # 5a. Kiểm tra xem tài khoản có bị Admin chặn không
            if user.is_blocked:
                print(f"Login FAILED for {email}: Account blocked")  # Debug
                return jsonify({"success": False,
                                "message": "Your account has been locked. Please contact the administrator."}), 403  # 403 Forbidden

            # 5b. Đăng nhập thành công:
            session.clear()  # Xóa session cũ (nếu có) để đảm bảo sạch sẽ
            session['db_user_id'] = user.id  # Lưu ID người dùng từ database vào session

            # Tạo và lưu thông tin người dùng cơ bản vào session để dễ truy cập ở các trang khác
            # và để hàm get_current_user_info() có thể lấy nhanh
            actual_user_info = {
                'name': user.name,
                'display_name': user.display_name,
                'email': user.email,
                'picture': user.picture_url,
                'is_admin': user.is_admin  # Quan trọng để phân quyền trong template (ví dụ: hiển thị menu Admin)
            }
            session['user_info'] = actual_user_info
            print(f"Login SUCCESS for {email}")  # Debug

            # Trả về JSON báo thành công cho client (AJAX)
            return jsonify({"success": True, "message": "Login successful!"}) # HTTP 200 OK (mặc định)
        else:
            # Đăng nhập thất bại: Sai email, sai mật khẩu, hoặc user đăng nhập bằng Google và chưa đặt mật khẩu hệ thống.
            print(f"Login FAILED for {email}: Invalid credentials or no password_hash set for this email.")  # Debug
            return jsonify({"success": False, "message": "Incorrect email or password."}), 401 # 401 Unauthorized

    # Trường hợp khác (ví dụ: request không phải GET cũng không phải POST hợp lệ, không nên xảy ra với route này)
    return jsonify({"success": False, "message": "Method not supported."}), 405  # 405 Method Not Allowed


@app.route('/register', methods=['GET', 'POST'])
def register():
    """
    Xử lý yêu cầu đăng ký tài khoản mới bằng form.
    - GET: Hiển thị trang đăng ký.
    - POST: Xác thực dữ liệu từ form, tạo người dùng mới nếu hợp lệ,
            và chuyển hướng đến trang đăng nhập.
    """

    # 1. Nếu người dùng đã đăng nhập (qua session 'db_user_id' hoặc Google),
    #    chuyển hướng họ về trang chủ, không cho phép đăng ký lại.
    if session.get("db_user_id") or google.authorized:
        return redirect(url_for('home'))

    # 2. Xử lý POST request (khi người dùng submit form đăng ký)
    if request.method == 'POST':
        # Lấy dữ liệu từ form
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        agree_terms = request.form.get('agree_terms')  # Giá trị sẽ là 'on' nếu được chọn, None nếu không

        # 2a. Kiểm tra các trường input cơ bản
        if not name or not email or not password or not confirm_password:
            flash('Please fill in all information.', 'danger')
            return redirect(url_for('register'))  # Tải lại trang đăng ký để hiển thị lỗi

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return redirect(url_for('register'))

        if password != confirm_password:
            flash('Password and confirm password do not match.', 'danger')
            return redirect(url_for('register'))

        # 2b. KIỂM TRA CHECKBOX "ĐỒNG Ý ĐIỀU KHOẢN"
        # Nếu checkbox không được chọn, giá trị của 'agree_terms' khi lấy từ request.form.get() sẽ là None.
        if not agree_terms:
            flash('You must agree to the Terms of Service and Privacy Policy to register.', 'danger')
            return redirect(url_for('register'))

        # 2c. Kiểm tra xem email đã tồn tại trong database chưa
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('This email address is already in use. Please choose another email.', 'warning')
            return redirect(url_for('register'))

        # 2d. Nếu tất cả thông tin hợp lệ, tạo người dùng mới
        new_user = User(name=name, email=email)
        new_user.set_password(password)  # Hash mật khẩu trước khi lưu

        try:
            db.session.add(new_user)  # Thêm người dùng mới vào session của database
            db.session.commit()  # Lưu các thay đổi vào database

            # (Tùy chọn) Bạn có thể thêm một trường is_terms_agreed (Boolean) vào model User
            # và đặt giá trị True ở đây nếu bạn muốn lưu lại việc người dùng đã đồng ý.

            flash('Registration successful! Please log in with the account you just created.', 'success')
            # Chuyển hướng đến trang đăng nhập (hoặc trang chủ và tự mở modal login)
            # Hiện tại, chuyển đến /login, và route /login sẽ redirect về home?open_login_modal=true
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()  # Hoàn tác lại các thay đổi trong database nếu có lỗi
            flash(f'An error occurred during registration.: {str(e)}', 'danger')
            print(f"Error during user registration for email {email}: {e}")  # Log lỗi chi tiết ở server
            return redirect(url_for('register'))  # Quay lại trang đăng ký

    # 3. Nếu là GET request, chỉ cần hiển thị trang đăng ký
    # (Đối tượng form từ Flask-WTF sẽ được truyền vào đây nếu bạn dùng Flask-WTF)
    return render_template('register.html')


@app.route('/privacy-policy')
def privacy_policy_page():
    return "<h1>Chính sách Bảo mật (Privacy Policy)</h1><p>Nội dung sẽ được cập nhật sớm.</p>"


@app.route('/terms-of-service')
def terms_of_service_page():
    return "<h1>Điều khoản Dịch vụ (Terms of Service)</h1><p>Nội dung sẽ được cập nhật sớm.</p>"


def translate_with_deep_translator(text_to_translate, dest_lang='vi', src_lang='auto'):
    """
    Dịch một đoạn văn bản sang ngôn ngữ đích sử dụng GoogleTranslator từ thư viện deep-translator.
    Đồng thời ghi log lại thông tin của mỗi lần gọi API dịch.

    Args:
        text_to_translate (str): Đoạn văn bản cần dịch.
        dest_lang (str, optional): Mã ngôn ngữ đích (ví dụ: 'vi' cho tiếng Việt). Mặc định là 'vi'.
        src_lang (str, optional): Mã ngôn ngữ nguồn (ví dụ: 'en' cho tiếng Anh, 'auto' để tự động phát hiện).
                                 Mặc định là 'auto'.

    Returns:
        str: Đoạn văn bản đã dịch, hoặc văn bản gốc nếu có lỗi hoặc dịch không thành công/không thay đổi.
    """

    # 1. Kiểm tra đầu vào: Nếu không có text hoặc text không hợp lệ, trả về text gốc.
    if not text_to_translate or not isinstance(text_to_translate, str) or not text_to_translate.strip():
        # print(f"translate_with_deep_translator: Input không hợp lệ hoặc rỗng: '{text_to_translate}'") # Debug
        return text_to_translate

    # 2. Chuẩn bị thông tin để ghi log
    api_name = "deep_translator_google"  # Tên định danh cho API này trong log
    user_id_to_log = session.get("db_user_id")  # Lấy ID của người dùng hiện tại từ session (nếu có)

    # Tạo một đối tượng APILog mới. Mặc định success có thể là False, sẽ cập nhật sau.
    # Giới hạn request_details để không quá dài, ví dụ 100 ký tự đầu.
    log_entry = APILog(
        api_name=api_name,
        request_details=f"Text: {text_to_translate[:100]}...",  # Lưu một phần text request
        user_id=user_id_to_log,
        success=False  # Giả định ban đầu là thất bại, sẽ cập nhật nếu thành công
    )

    try:
        # 3. Thực hiện việc dịch sử dụng GoogleTranslator
        #    Khởi tạo đối tượng GoogleTranslator với ngôn ngữ nguồn và đích.
        #    Gọi phương thức translate() để dịch.
        # print(f"deep-translator: Đang dịch: '{text_to_translate[:50]}...' từ '{src_lang}' sang '{dest_lang}'") # Debug
        translated_text = GoogleTranslator(source=src_lang, target=dest_lang).translate(text_to_translate)

        # 4. Xử lý kết quả dịch
        if translated_text is None:
            # Trường hợp API trả về None (không dịch được)
            log_entry.error_message = "Translation returned None"
            print(f"deep-translator: Dịch trả về None cho '{text_to_translate[:50]}...'")
            # Văn bản gốc sẽ được trả về ở khối finally sau khi ghi log
        elif translated_text.strip().lower() == text_to_translate.strip().lower():
            # Trường hợp bản dịch giống hệt bản gốc (có thể do từ không cần dịch, hoặc API không tìm thấy bản dịch tốt hơn)
            log_entry.success = True  # Vẫn coi là một lượt gọi API thành công (không có exception)
            log_entry.error_message = "Translation result is the same as the original text."
            print(f"deep-translator: Bản dịch giống văn bản gốc cho '{text_to_translate[:50]}...'")
            # Sẽ trả về translated_text (là bản gốc)
        else:
            # Dịch thành công và có kết quả khác biệt
            log_entry.success = True
            # Thuộc tính status_code không được cung cấp trực tiếp bởi thư viện này cho mỗi lần dịch,
            # nên chúng ta có thể bỏ qua hoặc mặc định là 200 nếu thành công.
            # log_entry.status_code = 200
            print(f"deep-translator: Dịch thành công: '{translated_text[:50]}...'")
            # Sẽ trả về translated_text (bản dịch)

        # Trả về bản dịch nếu thành công và khác biệt, ngược lại trả về bản gốc.
        # Quyết định trả về bản dịch hay bản gốc được xử lý ở cuối, sau khi log.
        # Nếu thành công và khác biệt, return translated_text. Nếu không, return text_to_translate.
        # Dòng return này sẽ được xử lý bởi logic bên ngoài try-except-finally hoặc ở cuối hàm.

    except Exception as e:
        # 5. Xử lý nếu có bất kỳ lỗi nào xảy ra trong quá trình gọi API hoặc xử lý kết quả
        log_entry.success = False  # Đã được đặt mặc định
        log_entry.error_message = str(e)[:500]  # Giới hạn độ dài thông báo lỗi để không quá lớn trong DB
        print(f"Lỗi khi dùng deep-translator cho '{text_to_translate[:50]}...': {e}")
        # Văn bản gốc sẽ được trả về ở khối finally hoặc cuối hàm

    finally:
        # 6. Luôn ghi log vào database, bất kể thành công hay thất bại
        try:
            db.session.add(log_entry)
            db.session.commit()
        except Exception as db_e:
            db.session.rollback()  # Rollback nếu ghi log lỗi
            print(f"LỖI NGHIÊM TRỌNG: Không thể ghi API log vào database: {db_e}")

    # 7. Quyết định giá trị trả về cuối cùng
    if log_entry.success and translated_text and translated_text.strip().lower() != text_to_translate.strip().lower():
        return translated_text
    else:
        # Trả về văn bản gốc nếu:
        # - Dịch không thành công (log_entry.success là False)
        # - Dịch thành công nhưng kết quả là None hoặc giống hệt bản gốc
        return text_to_translate


def translate_text_libre_batch(texts_to_translate, target_lang="vi", source_lang="en"):
    """
    Dịch một danh sách các đoạn văn bản sử dụng API LibreTranslate (batch request).

    Args:
        texts_to_translate (list): Danh sách các chuỗi (str) cần dịch.
        target_lang (str, optional): Mã ngôn ngữ đích (ví dụ: 'vi' cho tiếng Việt). Mặc định là 'vi'.
        source_lang (str, optional): Mã ngôn ngữ nguồn (ví dụ: 'en' cho tiếng Anh). Mặc định là 'en'.
                                     LibreTranslate cũng hỗ trợ 'auto' cho một số trường hợp.

    Returns:
        list: Danh sách các chuỗi đã được dịch, theo đúng thứ tự của danh sách đầu vào.
              Nếu có lỗi xảy ra cho toàn bộ batch hoặc một mục không dịch được,
              nó sẽ trả về danh sách các chuỗi gốc.
    """

    # 1. Kiểm tra đầu vào: Nếu danh sách rỗng, trả về danh sách rỗng luôn.
    if not texts_to_translate:
        return []

    # 2. Định nghĩa URL của API LibreTranslate và chuẩn bị payload/headers
    LIBRETRANSLATE_API_URL = "https://libretranslate.de/translate"  # Instance công khai của LibreTranslate

    # Payload cho request API. LibreTranslate cho phép gửi một mảng các chuỗi trong trường 'q'
    # khi Content-Type là 'application/json'.
    payload = {
        "q": texts_to_translate,  # Danh sách các đoạn văn bản cần dịch
        "source": source_lang,  # Ngôn ngữ nguồn
        "target": target_lang,  # Ngôn ngữ đích
        "format": "text"  # Định dạng output là text thuần (không phải HTML)
    }
    headers = {
        "Content-Type": "application/json"  # Bắt buộc để API hiểu payload có 'q' là một mảng
    }

    # 3. Đặt thời gian chờ (timeout) cho request API
    #    Thời gian chờ cố định là 45 giây. Nếu danh sách texts_to_translate quá lớn hoặc
    #    các câu quá dài, bạn có thể cần tăng giá trị này hoặc xem xét việc chia nhỏ batch.
    timeout_duration = 45  # Đơn vị: giây

    try:
        # In thông báo debug trước khi gửi request
        print(
            f"Đang gửi batch translation request tới LibreTranslate với timeout: {timeout_duration}s cho {len(texts_to_translate)} câu."
        )

        # 4. Gửi POST request đến API LibreTranslate
        response = requests.post(
            LIBRETRANSLATE_API_URL,
            json=payload,  # Gửi payload dưới dạng JSON (requests sẽ tự đặt Content-Type từ headers)
            headers=headers,
            timeout=timeout_duration  # Đặt thời gian chờ cho request
        )

        # 5. Kiểm tra lỗi HTTP từ response
        #    response.raise_for_status() sẽ ném ra một exception (HTTPError)
        #    nếu mã trạng thái HTTP là lỗi (4xx hoặc 5xx).
        response.raise_for_status()

        # 6. Phân tích JSON response
        data = response.json()  # Chuyển đổi nội dung response thành dictionary Python

        # LibreTranslate thường trả về kết quả dịch batch trong một key là "translatedTexts" (một list các chuỗi)
        # hoặc đôi khi là một list các object, mỗi object có key "translatedText".
        # Instance libretranslate.de trả về {"translatedTexts": ["dịch 1", "dịch 2", ...]}
        translated_texts_list = data.get("translatedTexts")

        # 7. Kiểm tra kết quả dịch
        if translated_texts_list and isinstance(translated_texts_list, list) and \
                len(translated_texts_list) == len(texts_to_translate):
            # Nếu có danh sách kết quả, nó là list, và số lượng kết quả khớp với số lượng đầu vào
            print("Dịch batch thành công!")  # Debug
            return translated_texts_list  # Trả về danh sách các bản dịch
        else:
            # Nếu kết quả không như mong đợi (ví dụ: thiếu key, sai định dạng, số lượng không khớp)
            print(f"Lỗi dịch batch: Không tìm thấy 'translatedTexts' hoặc số lượng không khớp. Response: {data}")
            # Trả về danh sách các chuỗi gốc nếu có vấn đề với cấu trúc response
            return [str(text) for text in texts_to_translate]  # Đảm bảo mọi thứ là string

    except requests.exceptions.Timeout:
        # 8. Xử lý lỗi Timeout (nếu request vượt quá timeout_duration)
        print(f"Timeout ({timeout_duration}s) khi dịch batch cho: {texts_to_translate}")
        return [str(text) for text in texts_to_translate]  # Trả về gốc
    except requests.exceptions.RequestException as e:
        # 9. Xử lý các lỗi request khác (ví dụ: lỗi kết nối, lỗi HTTP đã được raise_for_status() ném ra)
        print(f"Lỗi Request API trong khi dịch batch: {e}")
        return [str(text) for text in texts_to_translate]  # Trả về gốc
    except Exception as e:
        # 10. Xử lý các lỗi không mong muốn khác (ví dụ: lỗi parse JSON nếu response không phải JSON, ...)
        print(f"Lỗi không mong muốn trong khi dịch batch: {e}")
        return [str(text) for text in texts_to_translate]  # Trả về gốc


def translate_single_text_libre(text_to_translate, target_lang="vi", source_lang="en", timeout=20):
    """
    Dịch một đoạn văn bản đơn lẻ sử dụng API LibreTranslate.

    Args:
        text_to_translate (str): Đoạn văn bản cần dịch.
        target_lang (str, optional): Mã ngôn ngữ đích. Mặc định là 'vi' (Tiếng Việt).
        source_lang (str, optional): Mã ngôn ngữ nguồn. Mặc định là 'en' (Tiếng Anh).
                                     LibreTranslate cũng có thể hỗ trợ 'auto' cho một số trường hợp.
        timeout (int, optional): Thời gian chờ tối đa cho request API (tính bằng giây). Mặc định là 20 giây.

    Returns:
        str: Đoạn văn bản đã dịch, hoặc văn bản gốc nếu có lỗi xảy ra hoặc không dịch được.
    """

    # 1. Kiểm tra đầu vào: Nếu không có text hoặc text chỉ là khoảng trắng, trả về text gốc.
    if not text_to_translate or not text_to_translate.strip():
        # print(f"translate_single_text_libre: Input rỗng hoặc chỉ chứa khoảng trắng, trả về gốc: '{text_to_translate}'") # Debug
        return text_to_translate

    # 2. Định nghĩa URL của API LibreTranslate và chuẩn bị payload
    LIBRETRANSLATE_API_URL = "https://libretranslate.de/translate"
    # Bạn có thể thử các instance LibreTranslate công khai khác nếu 'libretranslate.de' không ổn định:
    # Ví dụ: LIBRETRANSLATE_API_URL = "https://translate.argosopentech.com/translate"
    # (Lưu ý: API của argosopentech có thể yêu cầu gửi payload dưới dạng JSON (`json=payload`) thay vì `data=payload`
    # và cấu trúc response có thể khác một chút).

    # Payload cho request. Đối với request đơn lẻ gửi dưới dạng form data (mặc định của requests.post khi dùng `data=`),
    # các trường được đặt trực tiếp.
    payload = {
        "q": text_to_translate,  # Đoạn văn bản cần dịch
        "source": source_lang,  # Ngôn ngữ nguồn
        "target": target_lang,  # Ngôn ngữ đích
        "format": "text"  # Yêu cầu output là text thuần
    }

    try:
        # In thông báo debug trước khi gửi request (nếu cần)
        # print(f"Đang dịch đơn lẻ (LibreTranslate): '{text_to_translate[:30]}...' với timeout {timeout}s")

        # 3. Gửi POST request đến API LibreTranslate
        #    Sử dụng `data=payload` vì nhiều instance LibreTranslate (bao gồm libretranslate.de)
        #    mong đợi dữ liệu form (application/x-www-form-urlencoded).
        response = requests.post(
            LIBRETRANSLATE_API_URL,
            data=payload,  # Gửi payload dưới dạng form data
            timeout=timeout  # Đặt thời gian chờ cho request
        )

        # 4. Kiểm tra lỗi HTTP từ response
        #    response.raise_for_status() sẽ ném ra một exception (HTTPError)
        #    nếu mã trạng thái HTTP là lỗi (4xx hoặc 5xx).
        response.raise_for_status()

        # 5. Phân tích JSON response
        data = response.json()  # Chuyển đổi nội dung response thành dictionary Python

        # LibreTranslate thường trả về kết quả dịch trong một key là "translatedText"
        translated_text = data.get("translatedText")

        # 6. Kiểm tra và trả về kết quả dịch
        if translated_text:
            # print(f"Dịch đơn lẻ thành công (LibreTranslate): '{translated_text[:30]}...'") # Debug
            return translated_text  # Trả về bản dịch nếu có
        else:
            # Nếu key "translatedText" không có trong response hoặc giá trị của nó là None/rỗng
            print(
                f"Không tìm thấy 'translatedText' trong phản hồi đơn lẻ của LibreTranslate cho '{text_to_translate[:30]}...'. Phản hồi: {data}"
            )
            return text_to_translate  # Trả về văn bản gốc

    except requests.exceptions.Timeout:
        # 7. Xử lý lỗi Timeout (nếu request vượt quá `timeout`)
        print(f"Timeout ({timeout}s) khi dịch đơn lẻ bằng LibreTranslate cho: '{text_to_translate[:30]}...'")
        return text_to_translate  # Trả về văn bản gốc
    except requests.exceptions.RequestException as e:
        # 8. Xử lý các lỗi request khác (ví dụ: lỗi kết nối, lỗi HTTP đã được raise_for_status() ném ra)
        print(f"Lỗi Request API khi dịch đơn lẻ bằng LibreTranslate '{text_to_translate[:30]}...': {e}")
        return text_to_translate  # Trả về văn bản gốc
    except Exception as e:
        # 9. Xử lý các lỗi không mong muốn khác (ví dụ: lỗi parse JSON nếu response không phải JSON, ...)
        print(f"Lỗi không mong muốn khi dịch đơn lẻ bằng LibreTranslate '{text_to_translate[:30]}...': {e}")
        return text_to_translate  # Trả về văn bản gốc


def get_word_details_dictionaryapi(word):
    """
    Lấy thông tin chi tiết của một từ từ API dictionaryapi.dev.
    Bao gồm loại từ, định nghĩa tiếng Anh, câu ví dụ tiếng Anh, và phiên âm IPA.
    Hàm này cố gắng tìm định nghĩa đầu tiên có kèm câu ví dụ, nếu không sẽ lấy định nghĩa đầu tiên tìm được.
    Thông tin IPA cũng được trích xuất nếu có.
    Kết quả được ghi log vào bảng APILog.

    Args:
        word (str): Từ tiếng Anh cần tra cứu.

    Returns:
        list: Một danh sách CHỨA MỘT dictionary nếu tìm thấy thông tin phù hợp
              (ví dụ: [{"type": "noun", "definition_en": "...", "example_en": "...", "ipa": "/.../"}]).
              Trả về danh sách rỗng ([]) nếu không tìm thấy thông tin, có lỗi API, hoặc từ không tồn tại.
    """

    DICTIONARY_API_URL = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"

    # Chuẩn bị cho việc ghi log API call
    api_name = "dictionary_api"
    user_id_to_log = session.get("db_user_id")  # Lấy user_id từ session (nếu có)
    # Khởi tạo log entry, mặc định success là False, sẽ được cập nhật nếu thành công
    log_entry = APILog(api_name=api_name, request_details=f"Word: {word}", user_id=user_id_to_log, success=False)

    try:
        # 1. Gửi GET request đến API từ điển, đặt timeout để tránh chờ đợi vô hạn
        response = requests.get(DICTIONARY_API_URL, timeout=15)  # Tăng nhẹ timeout
        log_entry.status_code = response.status_code  # Ghi lại mã trạng thái HTTP

        # 2. Kiểm tra lỗi HTTP từ response (ví dụ: 404 Not Found, 500 Internal Server Error)
        response.raise_for_status()  # Nếu có lỗi, sẽ ném ra HTTPError và được bắt ở khối except

        # 3. Phân tích JSON response
        data = response.json()  # Chuyển đổi nội dung response thành list các dictionary Python

        # In ra để debug (có thể bỏ comment khi cần)
        # print(f"DEBUG: Dictionary API response for '{word}': {data}")

        # 4. Xử lý dữ liệu JSON nhận được
        if isinstance(data, list) and len(data) > 0:
            # API này thường trả về một mảng, chúng ta lấy phần tử đầu tiên (thường chứa thông tin chính của từ)
            first_entry_data = data[0]

            # 4a. Trích xuất thông tin phiên âm IPA
            ipa_text = "N/A"  # Giá trị mặc định nếu không tìm thấy IPA
            if first_entry_data.get("phonetics"):  # Kiểm tra xem có mục 'phonetics' không
                for phonetic_item in first_entry_data["phonetics"]:
                    if phonetic_item.get("text"):  # Ưu tiên lấy trường 'text' chứa IPA
                        ipa_text = phonetic_item.get("text")
                        break  # Lấy IPA đầu tiên tìm thấy và thoát vòng lặp

            # 4b. Tìm định nghĩa và ví dụ từ mục 'meanings'
            if first_entry_data.get("meanings"):
                for meaning_obj in first_entry_data[
                    "meanings"]:  # Một từ có thể có nhiều nhóm nghĩa (ví dụ: noun, verb)
                    part_of_speech = meaning_obj.get("partOfSpeech", "N/A")  # Lấy loại từ

                    if meaning_obj.get("definitions"):  # Mỗi nhóm nghĩa có thể có nhiều định nghĩa
                        first_definition_without_example = None  # Để lưu định nghĩa đầu tiên tìm được (kể cả không có ví dụ)

                        # Ưu tiên tìm định nghĩa có kèm câu ví dụ
                        for definition_obj_item in meaning_obj["definitions"]:
                            definition_en = definition_obj_item.get("definition")  # Câu giải thích nghĩa tiếng Anh
                            example_en = definition_obj_item.get("example")  # Câu ví dụ tiếng Anh

                            if definition_en:  # Chỉ xử lý nếu có câu định nghĩa
                                current_details = {
                                    "type": part_of_speech,
                                    "definition_en": definition_en,
                                    "example_en": example_en if example_en else "N/A",  # "N/A" nếu không có ví dụ
                                    "ipa": ipa_text  # Thêm thông tin IPA đã lấy được ở trên
                                }

                                if example_en:  # Nếu định nghĩa này có câu ví dụ
                                    log_entry.success = True  # Đánh dấu API call thành công
                                    # Trả về ngay định nghĩa này (được ưu tiên vì có ví dụ)
                                    # Hàm sẽ kết thúc ở đây nếu tìm thấy.
                                    return [current_details]

                                if not first_definition_without_example:
                                    # Nếu chưa lưu định nghĩa nào, lưu lại định nghĩa đầu tiên này
                                    # (phòng trường hợp không có định nghĩa nào có ví dụ)
                                    first_definition_without_example = current_details

                        # Nếu đã duyệt hết các định nghĩa trong một 'meaning_obj' mà không có cái nào có ví dụ,
                        # thì sử dụng 'first_definition_without_example' đã lưu (nếu có)
                        if first_definition_without_example:
                            log_entry.success = True  # Đánh dấu API call thành công
                            # Trả về định nghĩa đầu tiên tìm được (không có ví dụ)
                            # Hàm sẽ kết thúc ở đây nếu tìm thấy.
                            return [first_definition_without_example]

            # 4c. Trường hợp không tìm thấy định nghĩa nào trong 'meanings' nhưng vẫn lấy được IPA
            if ipa_text != "N/A":  # Và chưa return ở trên (nghĩa là không có definition_en nào hợp lệ)
                log_entry.success = True  # Coi như thành công nếu lấy được ít nhất IPA
                return [{
                    "type": "N/A",
                    "definition_en": "No definition found.",
                    "example_en": "N/A",
                    "ipa": ipa_text
                }]

            # Nếu không có định nghĩa hợp lệ nào và cũng không có IPA (hoặc IPA là "N/A" và không có definition)
            log_entry.error_message = "No valid definitions or usable IPA found in API response."
            print(f"No valid definitions or IPA found for '{word}'.")
        else:  # data không phải list hoặc list rỗng
            log_entry.error_message = "No detailed entry found or unexpected format from API."
            print(f"No detailed entry found or unexpected format for '{word}'.")

    except requests.exceptions.Timeout as e:
        log_entry.error_message = f"Timeout: {str(e)}"
        print(f"Timeout when calling Dictionary API for '{word}': {e}")
    except requests.exceptions.HTTPError as http_err:
        # log_entry.status_code đã được set ở đầu khối try
        log_entry.error_message = f"HTTP Error: {str(http_err)}"
        print(f"Lỗi HTTP khi gọi Dictionary API cho từ '{word}': {http_err}")
    except requests.exceptions.RequestException as e:
        log_entry.error_message = f"Request Error: {str(e)}"
        print(f"Lỗi Request API cho từ '{word}' với Dictionary API: {e}")
    except Exception as e:  # Các lỗi khác, ví dụ lỗi parse JSON nếu response không phải JSON
        log_entry.error_message = f"Unexpected Error: {str(e)}"
        print(f"Lỗi không mong muốn khi lấy chi tiết cho từ '{word}': {e}")

    finally:
        # 5. Luôn ghi log vào database, bất kể thành công hay thất bại
        #    Điều này đảm bảo mọi nỗ lực gọi API đều được ghi lại.
        try:
            db.session.add(log_entry)
            db.session.commit()
        except Exception as db_e:
            db.session.rollback()  # Hoàn tác nếu việc ghi log vào DB bị lỗi
            print(f"CRITICAL ERROR: Could not write API log to database: {db_e}")
            # Trong trường hợp này, log_entry có thể không được lưu, nhưng hàm vẫn nên tiếp tục.

    # 6. Nếu không tìm thấy thông tin phù hợp nào hoặc có lỗi, trả về danh sách rỗng
    return []


@app.route('/enter-words',
           methods=['GET', 'POST'])
# Route này xử lý cả GET (hiển thị trang) và POST (submit form generate)
@login_required  # <<< Bỏ comment dòng này để kích hoạt bảo vệ route
def enter_words_page():
    """
    Hiển thị trang "Enter New Words" và xử lý việc người dùng nhập từ,
    generate thông tin (loại từ, nghĩa, ví dụ, IPA) và hiển thị kết quả.
    Hỗ trợ việc thêm từ vào một danh sách cụ thể nếu target_list_id được cung cấp.
    Sử dụng Flask-WTF để xử lý form và CSRF protection.
    """

    log_user_activity(session.get("db_user_id"), 'accessed_enter_words_page')
    form = GenerateWordsForm()

    display_user_info = get_current_user_info()

    user_lists = []
    target_list_info = None

    # current_user_db_id đã có sẵn từ decorator @login_required
    # Nếu decorator được dùng, current_user_db_id sẽ là user.id
    # Nếu không dùng decorator và bạn vẫn cần ID, thì dòng này là cần thiết
    current_user_db_id = session.get("db_user_id")

    # Nếu người dùng đã đăng nhập, lấy danh sách các list của họ
    # Kiểm tra display_user_info ở đây là tốt vì nó cũng xác nhận user có tồn tại.
    if display_user_info and current_user_db_id:
        user_lists = VocabularyList.query.filter_by(user_id=current_user_db_id).order_by(
            VocabularyList.name.asc()).all()

    if request.method == 'GET':
        target_list_id_from_url = request.args.get('target_list_id', type=int)
        if target_list_id_from_url and current_user_db_id:
            list_obj = VocabularyList.query.filter_by(id=target_list_id_from_url, user_id=current_user_db_id).first()
            if list_obj:
                target_list_info = {"id": list_obj.id, "name": list_obj.name}
                flash(f"You are adding words to the list: '{list_obj.name}'. The words will be saved to this list.",
                      "info")
                if form.target_list_id_on_post:
                    form.target_list_id_on_post.data = list_obj.id
            else:
                flash("The specified list was not found or you do not have permission.", "warning")
                return redirect(url_for('my_lists_page'))

    input_str = ""
    processed_results_dict = {}

    if form.validate_on_submit():
        input_str = form.words_input.data
        session['last_processed_input'] = input_str

        words_list = [word.strip() for word in input_str.split(',') if word.strip()]

        if words_list:
            for original_word in words_list:
                print(f"Đang xử lý từ: {original_word}")
                detailed_entries = get_word_details_dictionaryapi(original_word)

                # Khởi tạo dictionary rỗng cho từ hiện tại nếu nó chưa tồn tại hoặc không phải là list
                # Đây là dòng an toàn hơn để tránh KeyError nếu có bất kỳ logic nào
                # đã thay đổi kiểu dữ liệu của processed_results_dict[original_word]
                if original_word not in processed_results_dict or not isinstance(processed_results_dict[original_word],
                                                                                 list):
                    processed_results_dict[original_word] = []

                # Khởi tạo các biến với giá trị mặc định trước khi xử lý
                word_type = "N/A"
                ipa_text = "N/A"
                english_definition = "No English definition found."
                vietnamese_explanation = "Không tìm thấy giải thích tiếng Việt."
                example_en = "N/A"
                vietnamese_example_sentence = "Không có câu ví dụ."

                if detailed_entries:
                    entry_detail = detailed_entries[0]

                    # Cập nhật các giá trị từ API nếu có
                    word_type = entry_detail.get("type", word_type)
                    ipa_text = entry_detail.get("ipa", ipa_text)

                    english_definition_from_api = entry_detail.get("definition_en")
                    if english_definition_from_api and english_definition_from_api.strip():
                        english_definition = english_definition_from_api

                    example_en_from_api = entry_detail.get("example_en")
                    if example_en_from_api and example_en_from_api.strip():
                        example_en = example_en_from_api

                    # Dịch định nghĩa tiếng Anh
                    if english_definition != "No English definition found." and english_definition.lower() != "n/a":
                        if english_definition.lower() != original_word.lower():
                            translated_definition = translate_with_deep_translator(english_definition)
                            if translated_definition and translated_definition.strip().lower() != english_definition.strip().lower():
                                vietnamese_explanation = translated_definition
                            else:
                                print(
                                    f"  Dịch định nghĩa thất bại hoặc không thay đổi cho: '{english_definition[:50]}...'.")
                                vietnamese_explanation = "Không thể dịch giải thích này."
                        else:
                            translated_word_meaning = translate_with_deep_translator(original_word)
                            if translated_word_meaning and translated_word_meaning.strip().lower() != original_word.strip().lower():
                                vietnamese_explanation = translated_word_meaning
                            else:
                                print(f"  Dịch từ gốc (fallback) thất bại cho '{original_word}'.")
                                vietnamese_explanation = "Không thể dịch từ này."

                    # DỊCH CÂU VÍ DỤ NẾU CÓ VÀ HỢP LỆ
                    if example_en != "N/A":
                        translated_example = translate_with_deep_translator(example_en)
                        if translated_example and translated_example.strip().lower() != example_en.strip().lower():
                            vietnamese_example_sentence = translated_example
                        else:
                            print(f"  Dịch câu ví dụ thất bại hoặc không thay đổi cho: '{example_en[:50]}...'.")
                            vietnamese_example_sentence = "Không thể dịch câu ví dụ này."
                    else:
                        vietnamese_example_sentence = "Không có câu ví dụ."

                    processed_results_dict[original_word].append({
                        "type": word_type,
                        "definition_en": english_definition,
                        "definition_vi": vietnamese_explanation,
                        "example_sentence": example_en,
                        "example_sentence_vi": vietnamese_example_sentence,
                        "ipa": ipa_text
                    })
                else:  # Không tìm thấy chi tiết từ API từ điển (detailed_entries rỗng)
                    vietnamese_translation_of_word = translate_with_deep_translator(original_word)
                    processed_results_dict[original_word].append({
                        "type": "N/A",
                        "definition_en": original_word,
                        "definition_vi": vietnamese_translation_of_word if (
                                vietnamese_translation_of_word and vietnamese_translation_of_word.strip().lower() != original_word.strip().lower()) else "Không thể dịch từ này.",
                        "example_sentence": "N/A",
                        "example_sentence_vi": "Không có câu ví dụ.",
                        "ipa": "N/A"
                    })
                print(f"  Kết quả cho '{original_word}': {processed_results_dict[original_word]}")

        elif input_str:
            flash("Please enter valid words, separated by commas.", "info")
    if request.method == 'GET':
        if not target_list_info and not processed_results_dict:
            form.words_input.data = session.pop('last_processed_input', '')
            if not form.words_input.data:
                form.words_input.data = ''
        elif form.words_input.data is None:
            form.words_input.data = session.get('last_processed_input', '')

    return render_template('enter_words.html',
                           form=form,
                           user_info=display_user_info,
                           input_words_str=form.words_input.data or "",
                           results=processed_results_dict,
                           user_existing_lists=user_lists,
                           target_list_info=target_list_info)


# --- Sửa đổi hàm save_list_route ---
@app.route('/save-list', methods=['POST'])
# @login_required
def save_list_route():
    current_user_db_id = session.get("db_user_id")
    if current_user_db_id:
        log_user_activity(current_user_db_id, 'words_saved',
                          details={'list_id': request.get_json().get('existing_list_id') or 'new'})
    if not current_user_db_id:
        print("DEBUG: User not logged in for save_list_route.")  # DEBUG
        return jsonify({"success": False, "message": "Vui lòng đăng nhập để lưu danh sách."}), 401

    data = request.get_json()
    if not data:
        print("DEBUG: No JSON data received in save_list_route.")  # DEBUG
        return jsonify({"success": False, "message": "Không nhận được dữ liệu."}), 400

    print(f"DEBUG: Data received by save_list_route: {data}")  # DEBUG: In toàn bộ payload

    vocabulary_items_data = data.get('words')
    list_name_from_input = data.get('list_name')
    existing_list_id = data.get('existing_list_id')

    if not vocabulary_items_data or not isinstance(vocabulary_items_data, list) or len(vocabulary_items_data) == 0:
        print("DEBUG: No vocabulary items to save.")  # DEBUG
        return jsonify({"success": False, "message": "Không có từ vựng nào để lưu."}), 400

    target_list = None
    is_new_list = False

    if existing_list_id:
        target_list = VocabularyList.query.filter_by(id=existing_list_id, user_id=current_user_db_id).first()
        if not target_list:
            print(
                f"DEBUG: Existing list ID {existing_list_id} not found or not owned by user {current_user_db_id}.")  # DEBUG
            return jsonify(
                {"success": False, "message": "Không tìm thấy danh sách hiện có hoặc bạn không có quyền."}), 403
    elif list_name_from_input and list_name_from_input.strip():
        cleaned_list_name = list_name_from_input.strip()
        existing_list_with_same_name = VocabularyList.query.filter_by(user_id=current_user_db_id,
                                                                      name=cleaned_list_name).first()
        if existing_list_with_same_name:
            print(f"DEBUG: List name '{cleaned_list_name}' already exists for user {current_user_db_id}.")  # DEBUG
            return jsonify({"success": False,
                            "message": f"Bạn đã có một danh sách với tên '{cleaned_list_name}'. Vui lòng chọn tên khác."}), 400

        target_list = VocabularyList(name=cleaned_list_name, user_id=current_user_db_id)
        db.session.add(target_list)
        is_new_list = True
        print(f"DEBUG: Creating new list: {cleaned_list_name} for user {current_user_db_id}.")  # DEBUG
    else:
        print("DEBUG: Invalid list name or no existing list ID provided.")  # DEBUG
        return jsonify({"success": False,
                        "message": "Vui lòng cung cấp tên cho danh sách mới hoặc chọn một danh sách hiện có."}), 400

    try:
        for item_data in vocabulary_items_data:
            print(f"DEBUG: Processing item_data for word: {item_data.get('original_word')}")  # DEBUG
            print(
                f"DEBUG: example_sentence_vi from item_data: {item_data.get('example_sentence_vi')}")  # DEBUG: RẤT QUAN TRỌNG

            new_entry = VocabularyEntry(
                original_word=item_data.get('original_word'),
                word_type=item_data.get('word_type'),
                definition_en=item_data.get('definition_en'),
                definition_vi=item_data.get('definition_vi'),
                ipa=item_data.get('ipa'),
                example_en=item_data.get('example_en'),
                example_vi=item_data.get('example_sentence_vi'),  # DÒNG NÀY ĐÃ ĐƯỢC SỬA. KIỂM TRA LẠI CHÍNH TẢ
                user_id=current_user_db_id,
                vocabulary_list=target_list
            )
            db.session.add(new_entry)
            print(
                f"DEBUG: Added new_entry for '{new_entry.original_word}' with example_vi='{new_entry.example_vi}'.")  # DEBUG

        db.session.commit()
        print("DEBUG: Database commit successful.")  # DEBUG

        action_message = f"Đã thêm từ vào danh sách '{target_list.name}'." if existing_list_id else f"Đã tạo và lưu danh sách '{target_list.name}'."

        return jsonify({
            "success": True,
            "message": action_message,
            "list_id": target_list.id,
            "is_new_list": is_new_list
        })

    except Exception as e:
        db.session.rollback()
        print(f"ERROR: Exception during saving list/words for user {current_user_db_id}: {e}")  # DEBUG Lỗi chi tiết
        import traceback
        traceback.print_exc()  # DEBUG: In đầy đủ traceback trên server console

        if "UNIQUE constraint failed" in str(e):
            return jsonify(
                {"success": False, "message": "Có lỗi xảy ra, có thể do dữ liệu không hợp lệ hoặc bị trùng lặp."}), 400

        return jsonify({"success": False, "message": f"Lỗi server không mong muốn: {str(e)}"}), 500


@app.route('/my-lists')  # Định nghĩa route URL là /my-lists
# @login_required # Nếu bạn có decorator này, hãy sử dụng nó ở đây
def my_lists_page():
    """
    Hiển thị trang "My Lists" của người dùng đã đăng nhập.
    Trang này sẽ liệt kê tất cả các danh sách từ vựng (VocabularyList)
    mà người dùng hiện tại đã tạo.
    """
    log_user_activity(session.get("db_user_id"), 'accessed_my_lists_page')
    # 1. Kiểm tra xem người dùng đã đăng nhập chưa bằng cách lấy 'db_user_id' từ session.
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:
        # Nếu chưa đăng nhập, hiển thị thông báo flash và chuyển hướng về trang chủ.
        # Trang chủ có thể có logic JavaScript để tự động mở modal đăng nhập.
        flash("Please login to view your list.", "warning")
        return redirect(url_for('home'))  # Hoặc url_for('home', open_login_modal='true')

    # 2. Lấy thông tin của người dùng hiện tại đang đăng nhập.
    #    Hàm get_current_user_info() sẽ trả về một dictionary chứa thông tin
    #    như tên, email, ảnh đại diện, trạng thái admin, v.v., để sử dụng trong template (ví dụ: base.html).
    display_user_info = get_current_user_info()
    # (Bạn có thể thêm kiểm tra nếu display_user_info là None thì xử lý, nhưng @login_required hoặc kiểm tra session ở trên thường đã đảm bảo)

    # 3. Truy vấn database để lấy tất cả các đối tượng VocabularyList
    #    thuộc về người dùng hiện tại (dựa trên current_user_db_id).
    #    Sắp xếp các danh sách theo ngày tạo (created_at) giảm dần (mới nhất lên đầu).
    #    Bạn có thể thay đổi tiêu chí sắp xếp nếu muốn (ví dụ: theo tên VocabularyList.name.asc()).
    user_lists = VocabularyList.query.filter_by(user_id=current_user_db_id).order_by(
        VocabularyList.created_at.desc()).all()

    # In ra thông báo debug ở server để theo dõi (tùy chọn)
    print(f"Đang hiển thị {len(user_lists)} danh sách cho user_id {current_user_db_id}")

    # 4. Render template 'my_lists.html' và truyền các dữ liệu cần thiết vào:
    #    - user_info: Thông tin của người dùng đang đăng nhập (cho base.html và các phần chung).
    #    - my_vocabulary_lists: Danh sách các đối tượng VocabularyList của người dùng.
    return render_template('my_lists.html',
                           user_info=display_user_info,
                           my_vocabulary_lists=user_lists)


@app.route('/my-lists/<int:list_id>')
def list_detail_page(list_id):
    """
    Hiển thị trang chi tiết của một VocabularyList cụ thể.
    Bao gồm thông tin của danh sách và tất cả các VocabularyEntry (từ vựng) trong danh sách đó.
    Chỉ người dùng sở hữu danh sách mới có thể xem được.
    """
    log_user_activity(session.get("db_user_id"), 'accessed_list_detail_page', details={'list_id': list_id})

    # 1. Kiểm tra xem người dùng đã đăng nhập chưa.
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:
        # Nếu chưa đăng nhập, hiển thị thông báo và chuyển hướng về trang chủ (hoặc trang đăng nhập).
        flash("Please login to view list details.", "warning")
        return redirect(url_for('home'))  # Hoặc url_for('home', open_login_modal='true')

    # 2. Lấy thông tin của người dùng hiện tại đang đăng nhập.
    #    Thông tin này dùng cho base template (header, sidebar).
    display_user_info = get_current_user_info()
    # (Có thể thêm kiểm tra nếu display_user_info là None thì xử lý,
    #  nhưng kiểm tra session ở trên thường đã bao hàm)

    # 3. Lấy đối tượng VocabularyList từ database dựa trên list_id từ URL.
    #    QUAN TRỌNG: Phải lọc theo cả id của list VÀ user_id của người dùng hiện tại
    #    để đảm bảo người dùng chỉ xem được danh sách của chính họ.
    vocab_list = VocabularyList.query.filter_by(id=list_id, user_id=current_user_db_id).first()

    # 4. Kiểm tra xem VocabularyList có tồn tại và thuộc về người dùng không.
    if not vocab_list:
        # Nếu không tìm thấy list (do ID sai hoặc không thuộc quyền sở hữu),
        # hiển thị thông báo lỗi và chuyển hướng về trang "My Lists" của người dùng.
        flash("The word list was not found or you do not have access.", "danger")
        return redirect(url_for('my_lists_page'))

    # 5. Nếu VocabularyList hợp lệ, lấy tất cả các VocabularyEntry (từ vựng)
    #    thuộc về danh sách này.
    #    Sắp xếp các từ theo ngày thêm (added_at) tăng dần (từ cũ nhất đến mới nhất).
    #    Bạn có thể thay đổi tiêu chí sắp xếp nếu muốn (ví dụ: theo original_word).
    entries_in_list = VocabularyEntry.query.filter_by(list_id=vocab_list.id).order_by(
        VocabularyEntry.added_at.asc()).all()

    # In ra thông tin debug ở server (tùy chọn)
    print(
        f"Hiển thị chi tiết list '{vocab_list.name}' (ID: {vocab_list.id}) cho user {current_user_db_id} với {len(entries_in_list)} từ.")
    if entries_in_list:
        print(f"Entry đầu tiên trong list: {entries_in_list[0].original_word}")

    # 6. Render template 'list_detail.html' và truyền các dữ liệu cần thiết vào:
    #    - user_info: Thông tin của người dùng đang đăng nhập (cho base.html).
    #    - current_list: Đối tượng VocabularyList đang được xem chi tiết.
    #    - entries: Danh sách các đối tượng VocabularyEntry trong current_list.
    return render_template('list_detail.html',
                           user_info=display_user_info,
                           current_list=vocab_list,
                           entries=entries_in_list)


@app.route('/delete-list/<int:list_id>', methods=['POST'])  # Route cho Admin xóa list
def delete_list_route(list_id):
    """
    Xử lý yêu cầu xóa một VocabularyList.
    Route này có thể được gọi bởi Admin (nếu endpoint là 'delete_list_route')
    hoặc bởi người dùng thường (nếu endpoint là 'delete_my_vocabulary_list').
    Cần đảm bảo kiểm tra quyền sở hữu phù hợp.
    """

    # 1. Lấy ID của người dùng hiện tại đang thực hiện hành động từ session.
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:
        # Nếu không có user_id trong session, nghĩa là người dùng chưa đăng nhập.
        flash("Please log in to perform this action.", "warning")
        # Chuyển hướng về trang chủ hoặc trang đăng nhập.
        return redirect(url_for('home'))

        # 2. Tìm VocabularyList cần xóa trong database dựa trên list_id được cung cấp.
    #    Sử dụng query.get(id) là cách trực tiếp để lấy một đối tượng bằng khóa chính của nó.
    list_to_delete = VocabularyList.query.get(list_id)

    # 3. Kiểm tra xem danh sách có tồn tại không.
    if not list_to_delete:
        # Nếu không tìm thấy danh sách với ID đó, hiển thị thông báo lỗi.
        flash("No list found to delete.", "danger")
        # Chuyển hướng về trang danh sách của người dùng hoặc trang dashboard của admin.
        # (Cần xác định logic redirect phù hợp dựa trên ai đang gọi route này)
        # Nếu đây là route chung, có thể cần kiểm tra vai trò user để redirect đúng.
        # Giả sử redirect về 'my_lists_page' nếu là user thường, hoặc 'admin_dashboard' nếu là admin.
        # Hiện tại, code gốc của bạn redirect về 'my_lists_page'.
        return redirect(url_for('my_lists_page'))

    # 4. Kiểm tra quyền sở hữu: Đảm bảo người dùng hiện tại có quyền xóa danh sách này.
    #    - Nếu đây là route cho người dùng thường tự xóa list của họ, user_id của list phải khớp với current_user_db_id.
    #    - Nếu đây là route cho Admin xóa list của người dùng khác, Admin phải có quyền (đã được kiểm tra bởi @admin_required).
    #      Trong trường hợp Admin, có thể không cần kiểm tra user_id của list_to_delete với current_user_db_id (vì admin có quyền cao hơn).
    #      Tuy nhiên, logic hiện tại của bạn là kiểm tra quyền sở hữu, phù hợp cho người dùng tự xóa.
    if list_to_delete.user_id != current_user_db_id:
        # Nếu người dùng không sở hữu danh sách này, không cho phép xóa.
        flash("You do not have permission to delete this list.", "danger")
        return redirect(url_for('my_lists_page'))  # Hoặc một trang lỗi truy cập

    try:
        # Lấy tên danh sách để sử dụng trong thông báo flash sau khi xóa thành công.
        deleted_list_name = list_to_delete.name

        # 5. Thực hiện xóa danh sách khỏi database.
        #    Nhờ thiết lập `cascade="all, delete-orphan"` trong mối quan hệ giữa
        #    VocabularyList và VocabularyEntry (trong model VocabularyList),
        #    tất cả các VocabularyEntry (từ vựng) liên quan đến danh sách này
        #    sẽ tự động bị xóa theo khỏi database.
        db.session.delete(list_to_delete)
        db.session.commit()  # Lưu các thay đổi vào database.

        # Hiển thị thông báo thành công cho người dùng.
        flash(f"Successfully deleted list '{deleted_list_name}'.", "success")
        # Ghi log ở server (tùy chọn)
        print(f"User {current_user_db_id} đã xóa list ID {list_id} ('{deleted_list_name}')")

    except Exception as e:
        # 6. Nếu có bất kỳ lỗi nào xảy ra trong quá trình tương tác với database,
        #    hoàn tác lại các thay đổi (rollback) để đảm bảo tính toàn vẹn dữ liệu.
        db.session.rollback()
        # Hiển thị thông báo lỗi cho người dùng.
        flash(f"An error occurred while deleting the list: {str(e)}", "danger")
        # Ghi log lỗi chi tiết ở server.
        print(f"Lỗi khi user {current_user_db_id} xóa list ID {list_id}: {e}")

    # 7. Sau khi xóa (hoặc nếu có lỗi và đã flash thông báo),
    #    chuyển hướng người dùng trở lại trang danh sách của họ.
    return redirect(url_for('my_lists_page'))


@app.route('/rename-list/<int:list_id>',
           methods=['POST'])  # Route này có thể là /admin/list/<int:list_id>/rename để rõ hơn
@admin_required  # Đảm bảo chỉ Admin mới có thể truy cập route này
def rename_list_route(list_id):
    """
    Xử lý yêu cầu của Admin để đổi tên một VocabularyList của người dùng.
    Yêu cầu này thường được gửi qua AJAX từ một modal trên giao diện Admin.
    """

    # 1. Kiểm tra xem Admin đã đăng nhập chưa (thường decorator @admin_required đã xử lý,
    #    nhưng kiểm tra lại không thừa, hoặc để lấy admin_id cho logging)
    admin_user_id = session.get("db_user_id")  # Giả sử admin cũng dùng db_user_id
    # (Nếu bạn có cơ chế session riêng cho admin, hãy dùng nó)
    # if not admin_user_id:
    #     # Mặc dù @admin_required đã chặn, nhưng để an toàn
    #     return jsonify({"success": False, "message": "Admin not logged in."}), 401

    # 2. Tìm VocabularyList cần đổi tên trong database dựa trên list_id.
    list_to_rename = VocabularyList.query.get(list_id)
    # Hoặc dùng get_or_404(list_id) nếu bạn muốn Flask tự trả về lỗi 404 HTML
    # (nhưng vì đây là AJAX, trả về JSON sẽ tốt hơn).

    if not list_to_rename:
        # Nếu không tìm thấy danh sách với ID đó, trả về lỗi 404 Not Found.
        return jsonify({"success": False, "message": "No list found to rename."}), 404

    # 3. Lấy dữ liệu JSON từ request (chứa tên mới của danh sách).
    data = request.get_json()
    if not data or 'new_name' not in data:
        # Nếu không có dữ liệu hoặc thiếu new_name, trả về lỗi 400 Bad Request.
        return jsonify({"success": False, "message": "New list name was not provided."}), 400

    new_name = data.get('new_name', '').strip()  # Lấy tên mới và loại bỏ khoảng trắng thừa.

    # 4. Validate tên mới.
    if not new_name:
        return jsonify({"success": False, "message": "New list name cannot be empty."}), 400
    if len(new_name) > 150:  # Ví dụ: giới hạn độ dài tên list (đồng bộ với model)
        return jsonify({"success": False, "message": "List name too long (max 150 characters)."}), 400

    # (Tùy chọn) Kiểm tra xem tên mới có trùng với một list khác của cùng người dùng sở hữu list này không.
    # Điều này giúp tránh việc một user có nhiều list trùng tên.
    owner_user_id = list_to_rename.user_id
    existing_list_with_new_name = VocabularyList.query.filter(
        VocabularyList.user_id == owner_user_id,
        VocabularyList.name == new_name,
        VocabularyList.id != list_id  # Loại trừ chính list đang được đổi tên
    ).first()

    if existing_list_with_new_name:
        return jsonify({"success": False,
                        "message": f"Người dùng này đã có một danh sách khác với tên '{new_name}'. Vui lòng chọn tên khác."}), 400

    try:
        # 5. Cập nhật tên của danh sách.
        list_to_rename.name = new_name
        db.session.commit()  # Lưu thay đổi vào database.

        # (Tùy chọn) Có thể flash message nếu sau đó bạn reload trang bằng JavaScript.
        # Tuy nhiên, với AJAX, client thường tự cập nhật UI hoặc hiển thị thông báo.
        # flash(f"Đã đổi tên danh sách (ID: {list_id}) thành '{new_name}'.", "success_admin")

        print(
            f"Admin (ID: {admin_user_id}) đã đổi tên list ID {list_id} thành '{new_name}' cho user ID {owner_user_id}")  # Debug

        # 6. Trả về JSON báo thành công.
        return jsonify({"success": True, "message": "Đổi tên danh sách thành công!", "new_name": new_name})

    except Exception as e:
        db.session.rollback()  # Hoàn tác nếu có lỗi khi commit.
        print(f"Lỗi khi Admin (ID: {admin_user_id}) đổi tên list ID {list_id}: {e}")  # Log lỗi chi tiết.
        return jsonify({"success": False, "message": f"Lỗi server khi đổi tên danh sách: {str(e)}"}), 500


@app.route('/admin/entry/<int:entry_id>/delete', methods=['POST'])  # Đặt tên route rõ ràng hơn cho Admin
@admin_required  # Đảm bảo chỉ Admin mới truy cập
def admin_delete_entry_route(entry_id):  # Đổi tên hàm cho rõ ràng hơn
    """
    Xử lý yêu cầu của Admin để xóa một VocabularyEntry cụ thể khỏi một danh sách.
    """
    admin_user_info = get_current_user_info()  # Lấy thông tin Admin đang đăng nhập

    # 1. Tìm VocabularyEntry cần xóa trong database.
    entry_to_delete = VocabularyEntry.query.get(entry_id)
    # Hoặc dùng get_or_404(entry_id) nếu bạn muốn Flask tự trả về lỗi 404 HTML (nhưng redirect thường tốt hơn cho UX ở đây).

    if not entry_to_delete:
        flash("No vocabulary entry found to delete.", "danger")
        # Redirect về một trang admin phù hợp, ví dụ dashboard hoặc trang quản lý user/list trước đó.
        # request.referrer có thể không đáng tin cậy hoặc không tồn tại.
        return redirect(request.referrer or url_for('admin_bp.dashboard'))  # Giả sử có admin_bp.dashboard

    # 2. Lấy thông tin cần thiết cho việc redirect và thông báo TRƯỚC KHI xóa.
    parent_list_id = entry_to_delete.list_id
    # Để redirect về trang admin xem chi tiết list của user, chúng ta cần owner_id của list đó.
    parent_list_owner_id = entry_to_delete.vocabulary_list.user_id
    entry_original_word = entry_to_delete.original_word

    # 3. Admin có quyền xóa entry của bất kỳ user nào, nên không cần kiểm tra quyền sở hữu của entry
    #    với admin_user_id, miễn là admin đã được xác thực bởi @admin_required.

    try:
        # 4. Thực hiện xóa VocabularyEntry.
        db.session.delete(entry_to_delete)
        db.session.commit()  # Lưu thay đổi vào database.

        flash(f"Successfully removed entry '{entry_original_word}' from list.",
              "success_admin")  # Use separate category for admin flash
        print(
            f"Admin ({admin_user_info.get('email')}) đã xóa entry ID {entry_id} ('{entry_original_word}') từ list ID {parent_list_id} của user ID {parent_list_owner_id}")  # Debug

    except Exception as e:
        db.session.rollback()  # Hoàn tác nếu có lỗi.
        flash(f"An error occurred while deleting item: {str(e)}", "danger_admin")
        print(f"Lỗi khi Admin ({admin_user_info.get('email')}) xóa entry ID {entry_id}: {e}")  # Log lỗi.

    # 5. Redirect Admin trở lại trang xem chi tiết danh sách từ vựng của người dùng đó.
    #    Sử dụng route mà Admin dùng để xem chi tiết list của user.
    return redirect(url_for('admin_view_list_entries_page', owner_user_id=parent_list_owner_id, list_id=parent_list_id))


class GenerateWordsForm(FlaskForm):
    """
    Định nghĩa form để người dùng nhập các từ cần generate thông tin.
    Sử dụng Flask-WTF để xử lý form và tích hợp CSRF protection tự động.
    """

    # Trường cho người dùng nhập danh sách các từ (cách nhau bằng dấu phẩy)
    words_input = TextAreaField(
        'Enter Words here:',  # Nhãn sẽ hiển thị cho trường này (nếu dùng form.label)
        validators=[DataRequired(message="Vui lòng nhập từ để generate.")]
        # DataRequired: Validator đảm bảo trường này không được để trống khi submit.
        # message: Thông báo lỗi tùy chỉnh nếu validation thất bại.
    )

    # Trường ẩn để lưu target_list_id khi người dùng generate từ
    # để thêm vào một danh sách cụ thể đã được chọn trước đó.
    # Giá trị này sẽ được gán từ server-side (trong route GET) hoặc giữ lại qua POST.
    target_list_id_on_post = HiddenField()

    # Nút submit cho form
    submit = SubmitField('Generate')  # Nhãn của nút submit


def calculate_time_difference(start_date):
    """
    Tính toán khoảng thời gian từ một ngày bắt đầu (start_date) đến hiện tại
    và trả về một chuỗi mô tả dễ đọc (ví dụ: "2 year/s, 3 month/s, 15 day/s ago").

    Args:
        start_date (datetime.datetime): Đối tượng datetime đại diện cho thời điểm bắt đầu.

    Returns:
        str: Chuỗi mô tả khoảng thời gian, hoặc "N/A" nếu start_date không hợp lệ,
             hoặc "Just joined!" nếu khoảng thời gian quá nhỏ.
    """

    # Kiểm tra nếu không có ngày bắt đầu hợp lệ
    if not start_date:
        return "N/A"

    now = datetime.utcnow()  # Lấy thời điểm hiện tại (UTC để nhất quán)
    delta = now - start_date  # Tính khoảng thời gian (timedelta object)

    # Tính số năm
    years = delta.days // 365
    remaining_days_after_years = delta.days % 365  # Số ngày còn lại sau khi đã trừ đi số năm tròn

    # Tính số tháng từ số ngày còn lại
    months = remaining_days_after_years // 30  # Ước lượng 1 tháng có 30 ngày
    remaining_days_after_months = remaining_days_after_years % 30  # Số ngày lẻ còn lại

    days = remaining_days_after_months  # Số ngày lẻ cuối cùng

    parts = []  # Danh sách để chứa các thành phần của chuỗi thời gian (năm, tháng, ngày)

    # Thêm "năm" vào danh sách nếu có
    if years > 0:
        parts.append(f"{years} year{'s' if years > 1 else ''}")  # Thêm 's' nếu số nhiều

    # Thêm "tháng" vào danh sách nếu có
    if months > 0:
        parts.append(f"{months} month{'s' if months > 1 else ''}")

    # Thêm "ngày" vào danh sách nếu có, HOẶC nếu không có năm/tháng nào (để không trả về chuỗi rỗng)
    if days > 0 or (not years and not months):
        parts.append(f"{days} day{'s' if days > 1 else ''}")

    # Nếu không có thành phần nào (ví dụ: delta rất nhỏ, vừa mới tạo)
    if not parts:
        return "Just joined!"  # Hoặc "A moment ago"

    # Nối các thành phần lại thành một chuỗi, cách nhau bằng dấu phẩy và thêm "ago" ở cuối
    return ", ".join(parts) + " ago"


@app.route('/profile', methods=['GET', 'POST'])
def profile_page():
    """
    Hiển thị trang Hồ sơ người dùng (User Profile) và xử lý việc đặt/thay đổi mật khẩu.
    - GET: Hiển thị thông tin hồ sơ, thống kê cơ bản.
    - POST: Xử lý yêu cầu thay đổi/đặt mật khẩu từ modal (gửi qua AJAX).
    """

    # 1. Kiểm tra xem người dùng đã đăng nhập chưa.
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:
        flash("Please login to view your profile.", "warning")
        # Chuyển hướng về trang chủ, có thể kèm tham số để JavaScript tự mở modal đăng nhập.
        return redirect(url_for('home', open_login_modal='true'))

        # 2. Lấy đối tượng User từ database dựa trên ID đã lưu trong session.
    user = User.query.get(current_user_db_id)
    if not user:
        # Nếu không tìm thấy user (ví dụ: session hỏng hoặc user đã bị xóa),
        # hiển thị lỗi, xóa session và chuyển hướng về trang chủ.
        flash("No user information found.", "danger")
        session.clear()
        return redirect(url_for('home'))

    # 3. Xử lý POST request (khi người dùng submit form đổi/đặt mật khẩu từ modal AJAX)
    if request.method == 'POST':
        # Lấy dữ liệu JSON từ request (vì JavaScript gửi dưới dạng JSON)
        data = request.get_json()
        if not data:
            # Nếu không có dữ liệu JSON, trả về lỗi 400 Bad Request.
            return jsonify({"success": False, "message": "Dữ liệu không hợp lệ hoặc thiếu."}), 400

        new_password = data.get('new_password')
        confirm_password = data.get('confirm_password')
        current_password_from_form = data.get(
            'current_password')  # Sẽ là None nếu người dùng đang đặt mật khẩu mới (form không có trường này)

        error_message = None  # Biến để lưu trữ thông báo lỗi validation
        can_set_password = False  # Cờ để xác định có được phép đặt/thay đổi mật khẩu không

        # 3a. Kiểm tra xem người dùng hiện tại đã có mật khẩu hay chưa
        if user.password_hash:  # Người dùng đã có mật khẩu -> họ đang THAY ĐỔI mật khẩu
            if not current_password_from_form:
                error_message = "Vui lòng nhập mật khẩu hiện tại của bạn."
            elif not user.check_password(current_password_from_form):  # Kiểm tra mật khẩu hiện tại có đúng không
                error_message = "Mật khẩu hiện tại không đúng."
            else:  # Mật khẩu hiện tại đúng
                can_set_password = True
        else:  # Người dùng chưa có mật khẩu (ví dụ: đăng nhập bằng Google lần đầu) -> họ đang ĐẶT mật khẩu mới
            can_set_password = True

        # 3b. Nếu được phép đặt/thay đổi mật khẩu (can_set_password là True) và chưa có lỗi nào ở trên
        if can_set_password and not error_message:
            if not new_password or not confirm_password:
                error_message = "Vui lòng nhập mật khẩu mới và xác nhận mật khẩu."
            elif len(new_password) < 6:  # Kiểm tra độ dài tối thiểu của mật khẩu mới
                error_message = "Mật khẩu mới phải có ít nhất 6 ký tự."
            elif new_password != confirm_password:  # Kiểm tra mật khẩu mới và xác nhận có khớp không
                error_message = "Mật khẩu mới và xác nhận mật khẩu không khớp."
            else:
                # Nếu tất cả validation cho mật khẩu mới đều OK
                try:
                    user.set_password(new_password)  # Gọi hàm set_password để hash và lưu mật khẩu mới
                    db.session.commit()  # Lưu thay đổi vào database

                    # (Tùy chọn) Cập nhật session['user_info'] để phản ánh việc đã có mật khẩu
                    if 'user_info' in session and session['user_info'] is not None:
                        session['user_info']['has_password'] = True
                        session.modified = True  # Đánh dấu session đã thay đổi để Flask lưu lại

                    print(f"User {user.email} đã cập nhật/đặt mật khẩu.")  # Debug log
                    # Trả về JSON báo thành công cho client AJAX
                    # JavaScript sẽ nhận được và có thể đóng modal, reload trang (để flash message hiển thị)
                    return jsonify({"success": True, "message": "Đã cập nhật/đặt mật khẩu thành công!"})
                except Exception as e:  # Bắt lỗi nếu có vấn đề khi commit vào DB
                    db.session.rollback()  # Hoàn tác thay đổi
                    error_message = f"Có lỗi xảy ra khi cập nhật mật khẩu: {str(e)}"
                    print(f"Lỗi khi user {user.email} cập nhật mật khẩu: {e}")  # Log lỗi chi tiết

        # 3c. Nếu có bất kỳ lỗi validation nào trong quá trình xử lý POST từ AJAX
        if error_message:
            # Trả về JSON báo lỗi và mã 400 Bad Request
            return jsonify({"success": False, "message": error_message}), 400

    # 4. Xử lý cho GET request (hiển thị trang profile với thông tin hiện tại)
    #    Hoặc khi POST request có lỗi validation và redirect về (nếu bạn dùng PRG pattern)
    #    Hoặc khi POST AJAX thành công và client tự reload trang.

    # Lấy các thông tin thống kê cho người dùng
    num_lists = VocabularyList.query.filter_by(user_id=user.id).count()
    num_entries = VocabularyEntry.query.filter_by(user_id=user.id).count()  # Giả định VocabularyEntry có user_id

    # Tính toán thời gian người dùng đã tham gia
    time_with_us_str = calculate_time_difference(user.created_at)  # Hàm này cần được định nghĩa ở đâu đó

    # Chuẩn bị dictionary chứa thông tin hồ sơ để truyền vào template
    user_profile_data = {
        "name": user.name,
        "display_name": user.display_name,
        "email": user.email,
        "picture": user.picture_url,
        "has_password": bool(user.password_hash),  # Rất quan trọng cho template để biết hiển thị form nào
        "google_id": user.google_id,
        "created_at": user.created_at,  # Cho hiển thị ngày tham gia
        "time_with_us": time_with_us_str  # Chuỗi thời gian đã đồng hành (ví dụ: "2 months, 10 days ago")
    }

    # Chuẩn bị dictionary chứa các thống kê (tương tự như dashboard)
    user_dashboard_stats = {
        "num_lists": num_lists,
        "num_entries": num_entries
    }

    # Lấy thông tin người dùng chung cho base template (header, sidebar)
    base_user_info = get_current_user_info()

    # Render template 'profile.html' với các dữ liệu đã chuẩn bị
    return render_template('profile.html',
                           user_profile_info=user_profile_data,  # Dữ liệu chi tiết cho trang profile
                           user_stats=user_dashboard_stats,  # Dữ liệu thống kê
                           user_info=base_user_info)  # Dữ liệu chung cho base.html


@app.route('/admin/user/<int:user_id_to_view>')  # Định nghĩa route URL, ví dụ: /admin/user/1, /admin/user/2
@admin_required  # Đảm bảo chỉ người dùng có quyền Admin mới có thể truy cập route này
def admin_view_user_detail(user_id_to_view):
    """
    Hiển thị trang chi tiết thông tin của một người dùng cụ thể cho Admin.
    Bao gồm thông tin cá nhân của người dùng đó và danh sách các VocabularyList mà họ đã tạo.
    """

    # 1. Lấy thông tin của Admin đang đăng nhập.
    #    Thông tin này thường được dùng để hiển thị ở header hoặc sidebar chung của trang (trong base.html).
    admin_user_info = get_current_user_info()
    # Hàm get_current_user_info() cần trả về một dictionary chứa thông tin người dùng hiện tại.

    # 2. Lấy đối tượng User (người dùng cần xem chi tiết) từ database
    #    dựa trên user_id_to_view được truyền vào từ URL.
    #    User.query.get_or_404(user_id_to_view) sẽ:
    #    - Trả về đối tượng User nếu tìm thấy.
    #    - Tự động kích hoạt một trang lỗi 404 Not Found nếu không tìm thấy User với ID đó.
    user_to_view = User.query.get_or_404(user_id_to_view)

    # 3. Lấy tất cả các đối tượng VocabularyList (danh sách từ vựng)
    #    thuộc về người dùng đang được xem (user_to_view).
    #    Sắp xếp các danh sách này theo ngày tạo (created_at) giảm dần (mới nhất lên đầu).
    #    Bạn có thể thay đổi tiêu chí sắp xếp nếu muốn (ví dụ: theo tên VocabularyList.name.asc()).
    user_vocabulary_lists = VocabularyList.query.filter_by(user_id=user_to_view.id).order_by(
        VocabularyList.created_at.desc()).all()

    # In ra thông báo debug ở server để theo dõi (tùy chọn)
    print(
        f"Admin ({admin_user_info.get('email') if admin_user_info else 'Unknown Admin'}) "
        f"đang xem chi tiết user '{user_to_view.email}' (ID: {user_id_to_view}) "
        f"với {len(user_vocabulary_lists)} danh sách."
    )

    # 4. Render template 'admin/user_detail.html' và truyền các dữ liệu cần thiết vào:
    #    - user_info: Thông tin của Admin đang đăng nhập (cho base.html và các phần chung).
    #    - viewed_user: Đối tượng User của người dùng mà Admin đang xem chi tiết.
    #    - vocabulary_lists_of_user: Danh sách các đối tượng VocabularyList của người dùng đó.
    return render_template('admin/user_detail.html',
                           user_info=admin_user_info,
                           viewed_user=user_to_view,
                           vocabulary_lists_of_user=user_vocabulary_lists)


@app.route('/admin/delete-user/<int:user_id_to_delete>', methods=['POST'])
@admin_required  # Đảm bảo chỉ Admin mới có thể truy cập route này
def admin_delete_user_route(user_id_to_delete):
    """
    Xử lý yêu cầu của Admin để xóa một tài khoản người dùng.
    Hành động này cũng sẽ xóa tất cả dữ liệu liên quan của người dùng đó
    (ví dụ: VocabularyLists và VocabularyEntries) nhờ vào thiết lập cascade delete trong model.
    """

    # 1. Lấy ID của Admin đang thực hiện hành động từ session (để kiểm tra tự xóa).
    admin_user_id = session.get("db_user_id")
    # (Nếu @admin_required đã kiểm tra đăng nhập, dòng này chủ yếu để lấy ID cho so sánh)

    # 2. Kiểm tra an toàn: Admin không thể tự xóa tài khoản của chính mình.
    if user_id_to_delete == admin_user_id:
        flash("You cannot delete your own account.", "danger")
        # Chuyển hướng về trang Admin Dashboard.
        return redirect(url_for('admin_dashboard'))  # Hoặc 'admin_bp.dashboard' nếu dùng blueprint

    # 3. Tìm người dùng cần xóa trong database dựa trên user_id_to_delete.
    user_to_delete = User.query.get(user_id_to_delete)
    # User.query.get(id) là cách nhanh để lấy đối tượng bằng khóa chính.
    # Nếu không tìm thấy, nó sẽ trả về None.

    # 4. Kiểm tra xem người dùng có tồn tại không.
    if not user_to_delete:
        flash("No user found to delete.", "danger")
        return redirect(url_for('admin_dashboard'))  # Hoặc 'admin_bp.dashboard'

    # 5. Kiểm tra an toàn bổ sung: Ngăn việc xóa một tài khoản Admin khác từ giao diện này.
    #    Đây là một biện pháp để tránh vô tình xóa hết Admin hoặc các lỗi nghiêm trọng.
    #    Việc quản lý tài khoản Admin cấp cao có thể cần một quy trình riêng biệt hơn.
    if user_to_delete.is_admin:
        flash("Cannot delete Admin account from this interface.", "danger")
        # Chuyển hướng về trang chi tiết của người dùng Admin đó (nơi không có nút xóa cho Admin).
        return redirect(url_for('admin_view_user_detail', user_id_to_view=user_id_to_delete))
        # Hoặc 'admin_bp.view_user_detail'

    try:
        # Lấy email của người dùng sắp bị xóa để sử dụng trong thông báo flash.
        user_email_deleted = user_to_delete.email

        # 6. Thực hiện xóa người dùng khỏi database.
        #    Quan trọng: Nếu bạn đã thiết lập `cascade="all, delete-orphan"`
        #    trong mối quan hệ từ User đến VocabularyList (trong model User),
        #    và từ VocabularyList đến VocabularyEntry (trong model VocabularyList),
        #    thì khi đối tượng User này bị xóa, SQLAlchemy sẽ tự động:
        #    - Xóa tất cả các VocabularyList thuộc về User này.
        #    - Xóa tất cả các VocabularyEntry thuộc về các VocabularyList đó.
        db.session.delete(user_to_delete)
        db.session.commit()  # Lưu các thay đổi (bao gồm cả cascade delete) vào database.

        # Hiển thị thông báo thành công cho Admin.
        flash(f"Successfully deleted user '{user_email_deleted}' and all related data.", "success")
        # Ghi log ở server (tùy chọn).
        print(f"Admin (ID: {admin_user_id}) đã xóa user ID {user_id_to_delete} ('{user_email_deleted}')")

    except Exception as e:
        # 7. Nếu có bất kỳ lỗi nào xảy ra trong quá trình tương tác với database,
        #    hoàn tác lại các thay đổi (rollback) để đảm bảo tính toàn vẹn dữ liệu.
        db.session.rollback()
        # Hiển thị thông báo lỗi cho Admin.
        flash(f"An error occurred while deleting the user: {str(e)}", "danger")
        # Ghi log lỗi chi tiết ở server.
        print(f"Lỗi khi Admin (ID: {admin_user_id}) xóa user ID {user_id_to_delete}: {e}")
        # Chuyển hướng về trang chi tiết của người dùng đó để Admin biết lỗi xảy ra với ai.
        return redirect(url_for('admin_view_user_detail', user_id_to_view=user_id_to_delete))
        # Hoặc 'admin_bp.view_user_detail'

    # 8. Sau khi xóa thành công, chuyển hướng Admin trở lại trang Admin Dashboard (danh sách người dùng).
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/user/<int:user_id_to_toggle>/toggle-block', methods=['POST'])
@admin_required  # Đảm bảo chỉ người dùng có quyền Admin mới có thể truy cập route này
def admin_toggle_block_user_route(user_id_to_toggle):
    """
    Xử lý yêu cầu của Admin để chặn hoặc bỏ chặn một tài khoản người dùng.
    Hành động này sẽ đảo ngược trạng thái 'is_blocked' của người dùng đó.
    """

    # 1. Lấy ID của Admin đang thực hiện hành động từ session.
    admin_user_id = session.get("db_user_id")
    # (Nếu @admin_required đã kiểm tra đăng nhập, dòng này chủ yếu để lấy ID cho so sánh và logging)

    # 2. Kiểm tra an toàn: Admin không thể tự chặn/bỏ chặn chính mình.
    if user_id_to_toggle == admin_user_id:
        flash("You cannot block/unblock yourself.", "danger")
        # Quay lại trang trước đó (nếu có) hoặc Admin Dashboard.
        # request.referrer chứa URL của trang mà từ đó request này được gửi đến.
        return redirect(request.referrer or url_for('admin_dashboard'))  # Hoặc 'admin_bp.dashboard'

    # 3. Tìm người dùng cần thay đổi trạng thái trong database.
    #    User.query.get_or_404(id) sẽ tự động trả về lỗi 404 nếu không tìm thấy user.
    user_to_toggle = User.query.get_or_404(user_id_to_toggle)

    # 4. Kiểm tra an toàn bổ sung: Không cho phép chặn/bỏ chặn tài khoản Admin khác.
    #    Đây là biện pháp để bảo vệ các tài khoản quản trị.
    if user_to_toggle.is_admin:
        flash("Cannot block/unblock other Admin accounts from this interface.", "danger")
        return redirect(request.referrer or url_for('admin_dashboard'))  # Hoặc 'admin_bp.dashboard'

    try:
        # 5. Đảo ngược trạng thái 'is_blocked' của người dùng.
        #    Nếu đang là True (bị chặn) -> thành False (bỏ chặn).
        #    Nếu đang là False (active) -> thành True (chặn).
        user_to_toggle.is_blocked = not user_to_toggle.is_blocked
        db.session.commit()  # Lưu thay đổi vào database.

        # Xác định hành động đã thực hiện để hiển thị thông báo phù hợp.
        action = "bỏ chặn" if not user_to_toggle.is_blocked else "chặn"

        # Hiển thị thông báo thành công.
        flash(f"Successfully {action} user '{user_to_toggle.email}'.", "success")
        # Ghi log ở server (tùy chọn).
        print(f"Admin (ID: {admin_user_id}) đã {action} user ID {user_id_to_toggle} ('{user_to_toggle.email}')")

    except Exception as e:
        # 6. Nếu có lỗi xảy ra trong quá trình tương tác với database, hoàn tác lại.
        db.session.rollback()
        # Hiển thị thông báo lỗi.
        flash(f"An error occurred while changing user status: {str(e)}", "danger")
        # Ghi log lỗi chi tiết ở server.
        print(f"Lỗi khi Admin (ID: {admin_user_id}) toggle block user ID {user_id_to_toggle}: {e}")

        # 7. Chuyển hướng người dùng trở lại trang phù hợp.
    #    Nếu request đến từ trang chi tiết của người dùng đó, quay lại trang đó.
    #    Nếu không, quay lại Admin Dashboard (danh sách người dùng).
    if request.referrer and f'/admin/user/{user_id_to_toggle}' in request.referrer:
        # Đảm bảo tên route và tham số đúng với định nghĩa route xem chi tiết user của Admin.
        return redirect(url_for('admin_view_user_detail', user_id_to_view=user_id_to_toggle))
        # Hoặc 'admin_bp.view_user_detail' nếu dùng blueprint.

    return redirect(url_for('admin_dashboard'))


@app.route('/admin/user/<int:owner_user_id>/list/<int:list_id>')
@admin_required  # Đảm bảo chỉ người dùng có quyền Admin mới có thể truy cập route này
def admin_view_list_entries_page(owner_user_id, list_id):
    """
    Hiển thị trang chi tiết các mục từ vựng (VocabularyEntry) trong một VocabularyList cụ thể
    của một người dùng, dành cho Admin xem.
    """

    # 1. Lấy thông tin của Admin đang đăng nhập.
    #    Thông tin này thường được dùng để hiển thị ở header hoặc sidebar chung của trang (trong base.html).
    admin_user_info = get_current_user_info()
    # Hàm get_current_user_info() cần trả về một dictionary chứa thông tin người dùng hiện tại.

    # 2. Lấy thông tin của người dùng sở hữu danh sách này (list_owner).
    #    Sử dụng owner_user_id từ URL để truy vấn.
    list_owner = User.query.get(owner_user_id)  # Lấy user bằng ID
    if not list_owner:
        # Nếu không tìm thấy người dùng với ID đó, hiển thị thông báo lỗi và chuyển hướng Admin
        # về trang Admin Dashboard (hoặc một trang quản lý người dùng phù hợp).
        flash(f"No user with ID {owner_user_id} found.", "danger")
        return redirect(url_for('admin_dashboard'))  # Hoặc 'admin_bp.dashboard' nếu dùng blueprint

    # 3. Lấy đối tượng VocabularyList từ database.
    #    Kiểm tra xem danh sách này có thực sự tồn tại với list_id được cung cấp
    #    VÀ có thuộc về owner_user_id (người dùng mà Admin đang xem) không.
    vocab_list = VocabularyList.query.filter_by(id=list_id, user_id=owner_user_id).first()

    if not vocab_list:
        # Nếu không tìm thấy danh sách (do ID sai hoặc không thuộc về người dùng đó),
        # hiển thị thông báo lỗi.
        flash(
            f"No vocabulary list with ID {list_id} found for user '{list_owner.email}', "
            f"or the list does not belong to this user.",
            "danger"
        )
        # Chuyển hướng Admin về trang chi tiết của người dùng đó (nơi họ có thể thấy các list khác).
        return redirect(url_for('admin_view_user_detail', user_id_to_view=owner_user_id))
        # Hoặc 'admin_bp.view_user_detail'

    # 4. Nếu VocabularyList hợp lệ, lấy tất cả các VocabularyEntry (từ vựng)
    #    thuộc về danh sách này.
    #    Sắp xếp các từ theo ngày thêm (added_at) tăng dần (từ cũ nhất đến mới nhất).
    #    Bạn có thể thay đổi tiêu chí sắp xếp nếu muốn (ví dụ: theo original_word).
    entries_in_list = VocabularyEntry.query.filter_by(list_id=vocab_list.id).order_by(
        VocabularyEntry.added_at.asc()).all()

    # In ra thông tin debug ở server để theo dõi (tùy chọn)
    print(
        f"Admin (ID: {admin_user_info.get('id_from_session_or_email') if admin_user_info else 'Unknown'}) "
        f"đang xem chi tiết list '{vocab_list.name}' (ID: {list_id}) của user '{list_owner.email}' (ID: {owner_user_id}) "
        f"với {len(entries_in_list)} từ."
    )

    # 5. Render template 'admin/admin_list_entries.html' và truyền các dữ liệu cần thiết vào:
    #    - user_info: Thông tin của Admin đang đăng nhập (cho base.html).
    #    - current_list: Đối tượng VocabularyList đang được xem chi tiết.
    #    - list_owner: Đối tượng User là chủ sở hữu của current_list.
    #    - entries: Danh sách các đối tượng VocabularyEntry trong current_list.
    return render_template('admin/admin_list_entries.html',
                           user_info=admin_user_info,
                           current_list=vocab_list,
                           list_owner=list_owner,
                           entries=entries_in_list)


@app.route('/google-complete-setup', methods=['GET', 'POST'])
def google_complete_setup_page():
    """
    Trang này cho phép người dùng vừa xác thực qua Google đặt mật khẩu
    để có thể đăng nhập bằng email/mật khẩu sau này.
    """
    # 1. Kiểm tra xem có dữ liệu tạm thời từ Google Auth không
    if 'google_auth_pending_setup' not in session:
        flash("There are no pending Google account setup requests. Please try signing in again.", "warning")
        return redirect(url_for('home'))

    # 2. Lấy thông tin người dùng từ session tạm thời
    pending_data = session['google_auth_pending_setup']
    email = pending_data.get('email')
    name = pending_data.get('name')
    picture = pending_data.get('picture')
    google_id = pending_data.get('google_id')

    # Nếu vì lý do nào đó không có email hoặc google_id, chuyển hướng về home
    if not email or not google_id:
        flash("Google credentials are incomplete. Please try again.", "danger")
        return redirect(url_for('home'))

    # 3. Xử lý POST request (khi người dùng submit form đặt mật khẩu)
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        # Validation mật khẩu
        if not new_password or not confirm_password:
            flash("Please enter new password and confirm password.", "danger")
        elif new_password != confirm_password:
            flash("New password and confirm password do not match.", "danger")
        elif len(new_password) < 6:
            flash("Password must be at least 6 characters.", "danger")
        else:
            try:
                # Tìm người dùng trong DB (có thể đã có tài khoản bằng email nhưng chưa có google_id/password)
                user = User.query.filter_by(google_id=google_id).first()
                if not user:
                    user = User.query.filter_by(email=email).first()

                if user:
                    # Nếu tìm thấy user, cập nhật mật khẩu và liên kết google_id nếu chưa có
                    user.set_password(new_password)
                    if not user.google_id:  # Liên kết nếu user đã có qua email nhưng chưa có google_id
                        user.google_id = google_id
                    if not user.name:  # Cập nhật tên nếu chưa có
                        user.name = name
                    if not user.picture_url:  # Cập nhật ảnh nếu chưa có
                        user.picture_url = picture
                    db.session.commit()
                else:
                    # Tạo người dùng mới hoàn toàn
                    new_user = User(
                        name=name,
                        email=email,
                        google_id=google_id,
                        picture_url=picture
                    )
                    new_user.set_password(new_password)
                    db.session.add(new_user)
                    db.session.commit()
                    user = new_user  # Gán lại user để thiết lập session

                # Thiết lập session cho người dùng sau khi hoàn tất
                session['db_user_id'] = user.id
                del session['google_auth_pending_setup']  # Xóa dữ liệu tạm thời
                flash('Account setup successful! You are now logged in.', 'success')
                return redirect(url_for('dashboard_page'))  # Chuyển hướng đến dashboard hoặc trang chủ

            except Exception as e:
                db.session.rollback()
                flash(f"An error occurred while setting up the account: {str(e)}", "danger")
                print(f"Error during Google setup for {email}: {e}")

    # 4. Xử lý GET request (hiển thị form)
    # Truyền thông tin người dùng từ Google (tạm thời) để hiển thị trên form
    # Dùng user_info=None vì trang này chưa cần thông tin người dùng từ DB,
    # nhưng base.html có thể dùng user_info nên cần để trống hoặc None.
    # Tuy nhiên, cần một base template đơn giản hơn hoặc truyền user_info rỗng.
    # Hoặc để base.html tự kiểm tra user_info.
    return render_template(
        'google_complete_setup.html',
        email=email,
        name=name,
        picture=picture
    )


# THÊM HÀM GHI LOG HOẠT ĐỘNG
def log_user_activity(user_id, activity_type, details=None):
    """Ghi lại một hoạt động của người dùng."""
    if user_id:
        activity = UserActivity(
            user_id=user_id,
            activity_type=activity_type,
            details=details
        )
        try:
            db.session.add(activity)
            db.session.commit()
            print(f"Logged activity for user {user_id}: {activity_type}")
        except Exception as e:
            db.session.rollback()
            print(f"Error logging activity for user {user_id}: {activity_type} - {e}")





@app.route('/admin/entry/<int:entry_id>/edit', methods=['POST'])
@admin_required  # Đảm bảo chỉ người dùng có quyền Admin mới có thể truy cập route này
def admin_edit_vocab_entry_route(entry_id):
    """
    Xử lý yêu cầu của Admin để chỉnh sửa một VocabularyEntry (mục từ vựng) cụ thể.
    Yêu cầu này thường được gửi qua AJAX từ một modal chỉnh sửa.
    """

    # 1. Lấy đối tượng VocabularyEntry cần chỉnh sửa từ database.
    #    User.query.get_or_404(id) sẽ tự động trả về lỗi 404 Not Found
    #    nếu không tìm thấy entry với ID đó, giúp đơn giản hóa việc kiểm tra.
    entry_to_edit = VocabularyEntry.query.get_or_404(entry_id)

    # 2. Lấy thông tin của Admin đang thực hiện hành động (để sử dụng trong logging).
    admin_user_info = get_current_user_info()
    # Hàm get_current_user_info() cần trả về một dictionary, ví dụ có key 'email'.

    # 3. Admin có quyền sửa bất kỳ entry nào (đã được xác thực bởi @admin_required).
    #    Không cần kiểm tra user_id của entry so với admin_user_id ở đây,
    #    vì mục đích là để Admin quản lý/kiểm duyệt nội dung.
    #    Nếu có các cấp độ Admin khác nhau, logic kiểm tra quyền chi tiết hơn có thể được thêm vào.

    # 4. Lấy dữ liệu JSON từ request được gửi bởi client (JavaScript).
    data = request.get_json()
    if not data:
        # Nếu không có dữ liệu JSON trong request, trả về lỗi 400 Bad Request.
        return jsonify({"success": False, "message": "Không có dữ liệu được gửi."}), 400

    try:
        # 5. Cập nhật các trường của đối tượng entry_to_edit với dữ liệu mới từ request.
        #    Sử dụng data.get('key', default_value) để lấy giá trị từ dictionary 'data'.
        #    Nếu key không tồn tại trong 'data', nó sẽ giữ lại giá trị hiện tại của trường đó trong entry_to_edit.
        #    Từ gốc (original_word) thường không nên cho phép sửa đổi ở đây để tránh nhầm lẫn,
        #    nếu muốn sửa từ gốc, có thể coi như tạo một entry mới và xóa entry cũ.

        entry_to_edit.word_type = data.get('word_type', entry_to_edit.word_type)
        entry_to_edit.definition_en = data.get('definition_en', entry_to_edit.definition_en)
        entry_to_edit.definition_vi = data.get('definition_vi', entry_to_edit.definition_vi)
        entry_to_edit.example_en = data.get('example_en', entry_to_edit.example_en)
        entry_to_edit.example_vi = data.get('example_vi', entry_to_edit.example_vi)
        # entry_to_edit.ipa = data.get('ipa', entry_to_edit.ipa) # Nếu bạn có trường IPA và cho phép sửa

        # (Tùy chọn) Cập nhật thêm các trường theo dõi nếu có trong model VocabularyEntry:
        # Ví dụ:
        # entry_to_edit.last_modified_by_admin_id = admin_user_info.get('id') # Giả sử admin_user_info có id
        # entry_to_edit.last_modified_at = datetime.utcnow()

        # 6. Lưu các thay đổi vào database.
        db.session.commit()

        # 7. (Tùy chọn) Gửi một thông báo flash. Thông báo này sẽ hiển thị cho Admin
        #    khi trang được tải lại (ví dụ, sau khi JavaScript nhận response thành công và reload trang).
        flash(f"Entry '{entry_to_edit.original_word}' successfully updated.", "success")

        # Ghi log ở server (tùy chọn).
        admin_email_for_log = admin_user_info.get('email') if admin_user_info else "Unknown Admin"
        print(f"Admin ({admin_email_for_log}) đã sửa entry ID {entry_id} ('{entry_to_edit.original_word}')")

        # 8. Trả về JSON báo thành công cho client AJAX.
        return jsonify({"success": True, "message": "Cập nhật mục từ thành công!"})

    except Exception as e:
        # 9. Nếu có bất kỳ lỗi nào xảy ra trong quá trình tương tác với database,
        #    hoàn tác lại các thay đổi (rollback) để đảm bảo tính toàn vẹn dữ liệu.
        db.session.rollback()
        # Ghi log lỗi chi tiết ở server.
        admin_email_for_log = admin_user_info.get('email') if admin_user_info else "Unknown Admin"
        print(f"Lỗi khi Admin ({admin_email_for_log}) sửa entry ID {entry_id}: {e}")
        # Trả về JSON báo lỗi server.
        return jsonify({"success": False, "message": f"Lỗi server khi cập nhật mục từ: {str(e)}"}), 500


@app.route('/admin/api-logs')
@admin_required
def admin_api_logs_page():
    admin_user_info = get_current_user_info()

    # --- PHÂN TRANG (PAGINATION) ---
    page = request.args.get('page', 1, type=int) # Lấy số trang từ URL (mặc định là 1)
    per_page = 10 # Số lượng log trên mỗi trang (bạn có thể thay đổi, ví dụ 20, 50, 100)

    # Lấy các bản ghi log API từ database với phân trang
    # paginate() trả về một đối tượng Pagination
    # .options(db.load_only(APILog.id, APILog.api_name, ...)) # Tùy chọn: chỉ tải các cột cần thiết để tối ưu
    pagination = APILog.query.order_by(APILog.timestamp.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False # Nếu page number không hợp lệ, không báo lỗi 404
    )

    logs = pagination.items # Lấy danh sách các log cho trang hiện tại

    # --- THỐNG KÊ TỔNG QUAN (GIỮ NGUYÊN) ---
    total_calls = APILog.query.count()
    successful_calls = APILog.query.filter_by(success=True).count()
    failed_calls = total_calls - successful_calls

    calls_by_api_name = db.session.query(
        APILog.api_name,
        func.count(APILog.id).label('count'),
        func.sum(case((APILog.success == True, 1), else_=0)).label('successful'),
        func.sum(case((APILog.success == False, 1), else_=0)).label('failed')
    ).group_by(APILog.api_name).all()

    stats = {
        "total_calls": total_calls,
        "successful_calls": successful_calls,
        "failed_calls": failed_calls,
        "calls_by_api_name": calls_by_api_name
    }

    # --- TRUYỀN DỮ LIỆU VÀO TEMPLATE ---
    return render_template('admin/api_logs.html',
                           user_info=admin_user_info,
                           logs=logs,
                           stats=stats,
                           pagination=pagination) # TRUYỀN ĐỐI TƯỢNG PHÂN TRANG MỚI VÀO

@app.route('/my-lists/<int:list_id_to_delete>/delete', methods=['POST'])
# @login_required # Nếu bạn đã có decorator này, hãy sử dụng nó ở đây để thay thế cho kiểm tra session thủ công
def delete_my_vocabulary_list(list_id_to_delete):
    """
    Xử lý yêu cầu của người dùng để xóa một VocabularyList (danh sách từ vựng) của chính họ.
    Hành động này cũng sẽ xóa tất cả các VocabularyEntry liên quan nhờ cascade delete.
    Chỉ chấp nhận phương thức POST.
    """

    # 1. Kiểm tra xem người dùng đã đăng nhập chưa.
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:
        # Nếu chưa đăng nhập, hiển thị thông báo và chuyển hướng.
        flash("Please log in to perform this action.", "warning")
        return redirect(url_for('home'))  # Hoặc url_for('login') nếu có trang login riêng

    # 2. Tìm VocabularyList cần xóa trong database dựa trên list_id_to_delete từ URL.
    list_to_delete = VocabularyList.query.get(list_id_to_delete)
    # query.get(id) là cách hiệu quả để lấy một đối tượng bằng khóa chính.

    # 3. Kiểm tra xem danh sách có thực sự tồn tại không.
    if not list_to_delete:
        # Nếu không tìm thấy danh sách, báo lỗi và chuyển hướng về trang "My Lists".
        flash("No list found to delete.", "danger")
        return redirect(url_for('my_lists_page'))

    # 4. QUAN TRỌNG: Kiểm tra quyền sở hữu.
    #    Đảm bảo rằng danh sách này thực sự thuộc về người dùng hiện tại đang đăng nhập.
    if list_to_delete.user_id != current_user_db_id:
        # Nếu không phải, người dùng không có quyền xóa danh sách này.
        flash("You do not have permission to delete this list.", "danger")
        return redirect(url_for('my_lists_page'))  # Chuyển hướng về trang "My Lists" của họ.

    try:
        # Lấy tên danh sách trước khi xóa để sử dụng trong thông báo flash.
        list_name_deleted = list_to_delete.name

        # 5. Thực hiện xóa danh sách khỏi database.
        #    Do đã thiết lập `cascade="all, delete-orphan"` trong mối quan hệ
        #    giữa VocabularyList và VocabularyEntry (trong model VocabularyList),
        #    việc xóa VocabularyList này sẽ tự động xóa tất cả các VocabularyEntry
        #    liên kết với nó.
        db.session.delete(list_to_delete)
        db.session.commit()  # Lưu các thay đổi (bao gồm cả cascade delete) vào database.

        # Hiển thị thông báo xóa thành công.
        flash(f"Successfully deleted list '{list_name_deleted}'.", "success")
        # Ghi log ở server (tùy chọn).
        print(
            f"User {current_user_db_id} đã xóa list ID {list_id_to_delete} ('{list_name_deleted}') của chính họ."
        )

    except Exception as e:
        # 6. Nếu có bất kỳ lỗi nào xảy ra trong quá trình tương tác với database,
        #    hoàn tác lại các thay đổi (rollback) để đảm bảo tính toàn vẹn dữ liệu.
        db.session.rollback()
        # Hiển thị thông báo lỗi cho người dùng.
        flash(f"An error occurred while deleting the list: {str(e)}", "danger")
        # Ghi log lỗi chi tiết ở server.
        print(f"Lỗi khi user {current_user_db_id} xóa list ID {list_id_to_delete}: {e}")

    # 7. Sau khi xóa (hoặc nếu có lỗi và đã flash thông báo),
    #    chuyển hướng người dùng trở lại trang "My Lists" của họ.
    return redirect(url_for('my_lists_page'))


@app.route('/my-lists/entry/<int:entry_id>/delete', methods=['POST'])
# @login_required # Nếu bạn đã có decorator này, hãy sử dụng nó ở đây để thay thế cho kiểm tra session thủ công
def delete_my_vocab_entry(entry_id):
    """
    Xử lý yêu cầu của người dùng để xóa một VocabularyEntry (mục từ vựng) cụ thể
    khỏi một trong các danh sách từ vựng của họ.
    Chỉ chấp nhận phương thức POST.
    """

    # 1. Kiểm tra xem người dùng đã đăng nhập chưa.
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:
        # Nếu chưa đăng nhập, hiển thị thông báo và chuyển hướng.
        flash("Please log in to perform this action.", "warning")
        return redirect(url_for('home'))  # Hoặc url_for('login_page') nếu có trang login riêng

    # 2. Tìm VocabularyEntry cần xóa trong database dựa trên entry_id từ URL.
    entry_to_delete = VocabularyEntry.query.get(entry_id)
    # query.get(id) là cách hiệu quả để lấy một đối tượng bằng khóa chính.

    # 3. Kiểm tra xem mục từ vựng có thực sự tồn tại không.
    if not entry_to_delete:
        flash("No word found to delete.", "danger")
        # Cố gắng chuyển hướng người dùng về trang trước đó họ đã truy cập (request.referrer).
        # Nếu không có thông tin trang trước đó, chuyển hướng về trang "My Lists" chung.
        return redirect(request.referrer or url_for('my_lists_page'))

    # 4. QUAN TRỌNG: Kiểm tra quyền sở hữu.
    #    Đảm bảo rằng VocabularyEntry này thuộc về một VocabularyList
    #    mà người dùng hiện tại đang đăng nhập sở hữu.
    #    Cách kiểm tra an toàn là thông qua 'vocabulary_list' relationship để lấy 'user_id' của list cha.
    #    Điều này giả định rằng bạn đã thiết lập mối quan hệ `vocabulary_list` trong model `VocabularyEntry`
    #    (ví dụ: entry_to_delete.vocabulary_list.user_id).
    #    Hoặc, nếu bạn đã thêm trường user_id trực tiếp vào model VocabularyEntry và đảm bảo nó được gán đúng,
    #    bạn có thể dùng: if entry_to_delete.user_id != current_user_db_id: (như bạn đã comment lại)
    if entry_to_delete.vocabulary_list.user_id != current_user_db_id:
        # Nếu không phải, người dùng không có quyền xóa từ này.
        flash("You do not have permission to delete this word.", "danger")
        # Chuyển hướng về trang chi tiết của danh sách chứa từ này (nơi họ đang xem).
        return redirect(url_for('list_detail_page', list_id=entry_to_delete.list_id))

    # 5. Lấy thông tin cần thiết cho việc redirect và thông báo TRƯỚC KHI xóa.
    parent_list_id = entry_to_delete.list_id  # ID của danh sách cha, để redirect lại đúng trang.
    entry_original_word = entry_to_delete.original_word  # Từ gốc, để dùng trong thông báo.

    try:
        # 6. Thực hiện xóa VocabularyEntry khỏi database.
        db.session.delete(entry_to_delete)
        db.session.commit()  # Lưu các thay đổi vào database.

        # Hiển thị thông báo xóa thành công.
        flash(f"Successfully removed word '{entry_original_word}' from list.", "success")
        # Ghi log ở server (tùy chọn).
        print(
            f"User {current_user_db_id} đã xóa entry ID {entry_id} ('{entry_original_word}') khỏi list ID {parent_list_id}"
        )

    except Exception as e:
        # 7. Nếu có bất kỳ lỗi nào xảy ra trong quá trình tương tác với database,
        #    hoàn tác lại các thay đổi (rollback).
        db.session.rollback()
        # Hiển thị thông báo lỗi cho người dùng.
        flash(f"An error occurred while deleting the word: {str(e)}", "danger")
        # Ghi log lỗi chi tiết ở server.
        print(f"Lỗi khi user {current_user_db_id} xóa entry ID {entry_id}: {e}")

    # 8. Sau khi xóa (hoặc nếu có lỗi và đã flash thông báo),
    #    chuyển hướng người dùng trở lại trang chi tiết của danh sách mà từ đó vừa bị xóa.
    return redirect(url_for('list_detail_page', list_id=parent_list_id))


@app.route('/my-lists/entry/<int:entry_id>/edit', methods=['POST'])
# @login_required # Nếu bạn đã có decorator này, hãy sử dụng nó ở đây
def edit_my_vocab_entry(entry_id):
    """
    Xử lý yêu cầu của người dùng để chỉnh sửa một VocabularyEntry (mục từ vựng)
    trong một trong các danh sách của họ.
    Yêu cầu này được gửi qua AJAX từ một modal chỉnh sửa.
    Chỉ chấp nhận phương thức POST.
    """

    # 1. Kiểm tra xem người dùng đã đăng nhập chưa.
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:
        # Nếu chưa đăng nhập, trả về lỗi 401 Unauthorized (cho AJAX).
        return jsonify({"success": False, "message": "Vui lòng đăng nhập để thực hiện hành động này."}), 401

    # 2. Tìm VocabularyEntry cần chỉnh sửa trong database dựa trên entry_id.
    entry_to_edit = VocabularyEntry.query.get(entry_id)
    # query.get(id) là cách hiệu quả để lấy đối tượng bằng khóa chính.

    # 3. Kiểm tra xem mục từ vựng có thực sự tồn tại không.
    if not entry_to_edit:
        # Nếu không tìm thấy, trả về lỗi 404 Not Found.
        return jsonify({"success": False, "message": "Không tìm thấy mục từ vựng để sửa."}), 404

    # 4. QUAN TRỌNG: Kiểm tra quyền sở hữu.
    #    Đảm bảo rằng VocabularyEntry này thuộc về người dùng hiện tại đang đăng nhập.
    #    Bạn đang kiểm tra trực tiếp user_id trên entry_to_edit. Điều này là đúng nếu
    #    model VocabularyEntry của bạn có trường user_id được gán đúng khi tạo entry.
    #    Một cách khác (an toàn hơn nếu user_id trên entry có thể không đồng bộ) là kiểm tra qua list cha:
    #    if entry_to_edit.vocabulary_list.user_id != current_user_db_id:
    if entry_to_edit.user_id != current_user_db_id:
        # Nếu không phải, người dùng không có quyền sửa từ này. Trả về lỗi 403 Forbidden.
        return jsonify({"success": False, "message": "Bạn không có quyền sửa mục từ vựng này."}), 403

    # 5. Lấy dữ liệu JSON từ request được gửi bởi client (JavaScript từ modal).
    data = request.get_json()
    if not data:
        # Nếu không có dữ liệu JSON trong request, trả về lỗi 400 Bad Request.
        return jsonify({"success": False, "message": "Không có dữ liệu được gửi để cập nhật."}), 400

    try:
        # 6. Cập nhật các trường của đối tượng entry_to_edit với dữ liệu mới từ request.
        #    Sử dụng data.get('key', entry_to_edit.field_name) để lấy giá trị mới,
        #    nếu key không tồn tại trong data, nó sẽ giữ lại giá trị cũ của trường đó.
        #    Từ gốc (original_word) thường không nên cho phép sửa đổi qua form này.

        entry_to_edit.word_type = data.get('word_type', entry_to_edit.word_type)
        entry_to_edit.definition_en = data.get('definition_en', entry_to_edit.definition_en)
        entry_to_edit.definition_vi = data.get('definition_vi', entry_to_edit.definition_vi)
        entry_to_edit.example_en = data.get('example_en', entry_to_edit.example_en)
        entry_to_edit.example_vi = data.get('example_vi', entry_to_edit.example_vi)
        # entry_to_edit.ipa = data.get('ipa', entry_to_edit.ipa) # Nếu bạn cho phép sửa IPA

        # (Tùy chọn) Cập nhật thêm trường thời gian sửa đổi nếu có trong model VocabularyEntry:
        # from datetime import datetime
        # entry_to_edit.updated_at = datetime.utcnow()

        # 7. Lưu các thay đổi vào database.
        db.session.commit()

        # 8. Gửi thông báo flash. Thông báo này sẽ được hiển thị cho người dùng
        #    khi trang được tải lại (ví dụ, sau khi JavaScript ở client nhận được
        #    response thành công và thực hiện window.location.reload()).
        flash(f"Entry '{entry_to_edit.original_word}' successfully updated.", "success")

        # Ghi log ở server (tùy chọn).
        print(f"User {current_user_db_id} đã sửa entry ID {entry_id} ('{entry_to_edit.original_word}')")

        # 9. Trả về JSON báo thành công cho client AJAX.
        return jsonify({"success": True, "message": "Updated item successfully!"})

    except Exception as e:
        # 10. Nếu có bất kỳ lỗi nào xảy ra trong quá trình tương tác với database,
        #     hoàn tác lại các thay đổi (rollback).
        db.session.rollback()
        # Ghi log lỗi chi tiết ở server.
        print(f"Lỗi khi User {current_user_db_id} sửa entry ID {entry_id}: {e}")
        # Trả về JSON báo lỗi server.
        return jsonify({"success": False, "message": f"Server error while updating item: {str(e)}"}), 500


@app.route('/dashboard')  # Định nghĩa route URL là /dashboard
@login_required  # Nếu bạn có decorator này, hãy sử dụng nó ở đây
def dashboard_page():
    """
    Hiển thị trang Dashboard cá nhân cho người dùng đã đăng nhập.
    Bao gồm lời chào, thống kê cơ bản (số lượng list, số từ),
    danh sách các list từ vựng tạo gần đây, và các từ mới thêm gần đây.
    """
    current_user_db_id = session.get("db_user_id")
    log_user_activity(current_user_db_id, 'accessed_dashboard_page')
    # 1. Kiểm tra xem người dùng đã đăng nhập chưa.
    current_user_db_id = session.get("db_user_id")
    user = User.query.get(current_user_db_id)
    if not current_user_db_id:
        # Nếu chưa đăng nhập, hiển thị thông báo và chuyển hướng về trang chủ,
        # có thể kèm tham số để JavaScript tự mở modal đăng nhập.
        flash("Please log in to access dashboard.", "warning")
        return redirect(url_for('home', open_login_modal='true'))

    # 2. Lấy thông tin của người dùng hiện tại đang đăng nhập.
    #    Thông tin này dùng cho base template (header, sidebar) và để chào mừng người dùng.
    display_user_info = get_current_user_info()
    if not display_user_info:  # Trường hợp hiếm nếu session db_user_id có nhưng không lấy được user từ DB
        flash("Failed to load user information. Please log in again.", "danger")
        return redirect(url_for('logout'))  # Đăng xuất để làm sạch session

    # 3. Lấy các thông tin thống kê cho người dùng hiện tại.
    #    3a. Đếm tổng số VocabularyList mà người dùng này đã tạo.
    num_lists = VocabularyList.query.filter_by(user_id=current_user_db_id).count()

    #    3b. Đếm tổng số VocabularyEntry (từ vựng) mà người dùng này đã lưu
    #        (giả định model VocabularyEntry có trường user_id liên kết trực tiếp).
    num_entries = VocabularyEntry.query.filter_by(user_id=current_user_db_id).count()

    #    3c. Gom các thống kê vào một dictionary để dễ truyền vào template.
    stats = {
        "num_lists": num_lists,
        "num_entries": num_entries
    }

    # 4. Lấy một vài danh sách từ vựng được tạo gần đây nhất của người dùng.
    #    Ví dụ: lấy 3 danh sách, sắp xếp theo ngày tạo (created_at) giảm dần.
    recent_lists = VocabularyList.query.filter_by(user_id=current_user_db_id).order_by(
        VocabularyList.created_at.desc()).limit(3).all()

    # 5. Lấy một vài mục từ vựng (VocabularyEntry) được thêm vào gần đây nhất bởi người dùng.
    #    Ví dụ: lấy 5 từ, sắp xếp theo ngày thêm (added_at) giảm dần.
    recent_entries = VocabularyEntry.query.filter_by(user_id=current_user_db_id).order_by(
        VocabularyEntry.added_at.desc()).limit(5).all()

    # In ra thông tin debug ở server để theo dõi (tùy chọn)
    print(
        f"Dashboard for user ID {current_user_db_id}: Stats: {stats}, "
        f"{len(recent_lists)} recent lists, {len(recent_entries)} recent entries"
    )

    # 6. Render template 'dashboard.html' và truyền các dữ liệu cần thiết vào:
    #    - user_info: Thông tin của người dùng đang đăng nhập (cho base.html và lời chào).
    #    - user_stats: Dictionary chứa các thông tin thống kê (số list, số từ).
    #    - recent_lists: Danh sách các VocabularyList tạo gần đây.
    #    - recent_entries: Danh sách các VocabularyEntry thêm gần đây.

    # --- TÍNH TOÁN VÀ HIỂN THỊ THÔNG BÁO THÁNG TRƯỚC ---
    last_month_activity_message = None
    today = datetime.utcnow()
    # Tính ngày đầu và cuối của tháng trước
    # Tháng hiện tại
    first_day_of_current_month = datetime(today.year, today.month, 1)

    # Tháng trước:
    # Nếu tháng hiện tại là tháng 1, tháng trước là tháng 12 năm trước
    if today.month == 1:
        first_day_of_last_month = datetime(today.year - 1, 12, 1)
    else:
        first_day_of_last_month = datetime(today.year, today.month - 1, 1)

    # Để lấy ngày cuối cùng của tháng trước, lấy ngày đầu tiên của tháng hiện tại
    # và trừ đi 1 giây hoặc 1 ngày.
    # Hoặc đơn giản hơn: lấy ngày đầu tiên của tháng sau tháng trước, trừ 1 ngày.
    # Lấy ngày đầu tiên của tháng hiện tại, trừ 1 giây để có cuối tháng trước
    end_of_last_month = first_day_of_current_month - timedelta(seconds=1)

    # Tìm bất kỳ hoạt động nào của người dùng trong tháng trước
    # Chúng ta chỉ quan tâm đến các hoạt động học tập chính để tránh báo cáo sai
    # activity_types_to_count = ['accessed_enter_words_page', 'words_saved', 'accessed_list_detail_page'] # Tùy thuộc vào cách bạn định nghĩa "học"
    # Hoặc đơn giản là tất cả các hoạt động UserActivity

    activities_last_month = UserActivity.query.filter(
        UserActivity.user_id == current_user_db_id,
        UserActivity.timestamp >= first_day_of_last_month,
        UserActivity.timestamp <= end_of_last_month
    ).count()

    # THÊM ĐIỀU KIỆN KIỂM TRA NGƯỜI DÙNG CŨ HAY MỚI
    # Nếu người dùng được tạo TRONG THÁNG TRƯỚC hoặc SỚM HƠN, mới xem xét hoạt động.
    # Nếu user.created_at rơi vào sau end_of_last_month (tức là họ mới tạo tài khoản trong tháng này),
    # thì không cần kiểm tra hoạt động tháng trước.
    if user.created_at <= end_of_last_month:  #
        activities_last_month = UserActivity.query.filter(
            UserActivity.user_id == current_user_db_id,
            UserActivity.timestamp >= first_day_of_last_month,
            UserActivity.timestamp <= end_of_last_month
        ).count()

        if activities_last_month == 0:
            # Thêm thông tin về tháng để thông báo rõ ràng hơn cho người dùng
            month_name = first_day_of_last_month.strftime('%B')  # Tên tháng đầy đủ (ví dụ: June)
            year = first_day_of_last_month.year
            last_month_activity_message = f"You have not studied anything in the last month {month_name} year {year}."
    else:
        # Nếu người dùng mới tạo tài khoản trong tháng hiện tại, không hiển thị thông báo
        # last_month_activity_message vẫn sẽ là None.
        pass

    if activities_last_month == 0:
        last_month_activity_message = "You have not learned anything in the last month."

    return render_template('dashboard.html',
                           user_info=display_user_info,
                           user_stats=stats,
                           recent_lists=recent_lists,
                           recent_entries=recent_entries,
                           last_month_activity_message=last_month_activity_message)


@app.route('/profile/update-info', methods=['POST'])
def update_profile_info_route():
    """
    Xử lý yêu cầu của người dùng để cập nhật thông tin hồ sơ cá nhân của họ,
    ví dụ như 'display_name'.
    Chỉ chấp nhận phương thức POST (từ form trên trang profile).
    """

    # 1. Kiểm tra xem người dùng đã đăng nhập chưa.
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:
        # Nếu chưa đăng nhập, hiển thị thông báo và chuyển hướng về trang chủ.
        flash("Please login to update profile.", "warning")
        return redirect(url_for('home'))  # Hoặc url_for('login_page')

    # 2. Lấy đối tượng User cần cập nhật từ database.
    user_to_update = User.query.get(current_user_db_id)
    if not user_to_update:
        # Nếu không tìm thấy user (trường hợp hiếm nếu session hợp lệ), báo lỗi và về trang chủ.
        flash("Error: No user information found to update.", "danger")
        session.clear()  # Có thể xóa session hỏng
        return redirect(url_for('home'))

    # 3. Lấy dữ liệu mới từ form đã submit.
    #    request.form.get('display_name', '').strip() sẽ:
    #    - Lấy giá trị của trường 'display_name' từ form.
    #    - Nếu không có trường đó, trả về chuỗi rỗng '' làm giá trị mặc định.
    #    - .strip() để loại bỏ khoảng trắng thừa ở đầu và cuối.
    new_display_name = request.form.get('display_name', '').strip()

    # 4. Validate dữ liệu mới (ví dụ: kiểm tra độ dài).
    if len(new_display_name) > 100:  # Giả sử giới hạn là 100 ký tự
        flash("Display name too long (maximum 100 characters).", "danger")
        return redirect(url_for('profile_page'))  # Quay lại trang profile để hiển thị lỗi

    # 5. Cập nhật thông tin cho đối tượng User.
    #    Nếu new_display_name là một chuỗi rỗng sau khi strip(),
    #    gán user_to_update.display_name = None để xóa tên hiển thị tùy chỉnh,
    #    khi đó ứng dụng có thể fallback về hiển thị user.name gốc.
    #    Nếu new_display_name có giá trị, gán giá trị đó.
    user_to_update.display_name = new_display_name if new_display_name else None

    try:
        # 6. Lưu các thay đổi vào database.
        db.session.commit()
        flash("Profile information updated successfully!", "success")

        # 7. (Quan trọng) Cập nhật lại thông tin trong session['user_info']
        #    để các phần khác của ứng dụng (ví dụ: header, sidebar) hiển thị tên mới ngay lập tức
        #    mà không cần người dùng đăng xuất rồi đăng nhập lại.
        if 'user_info' in session and session['user_info'] is not None:
            # Cập nhật 'name' trong user_info để hiển thị (có thể là display_name hoặc name gốc)
            session['user_info']['name'] = new_display_name if new_display_name else user_to_update.name
            session['user_info'][
                'display_name'] = user_to_update.display_name  # Luôn cập nhật display_name trong session
            session.modified = True  # Đánh dấu session đã được sửa đổi để Flask lưu lại.

    except Exception as e:
        # 8. Nếu có lỗi khi commit vào database, hoàn tác lại thay đổi.
        db.session.rollback()
        flash(f"Error updating information: {str(e)}", "danger")
        print(f"Lỗi khi user {user_to_update.email} cập nhật display_name: {e}")  # Log lỗi chi tiết.

    # 9. Sau khi xử lý (thành công hoặc lỗi), chuyển hướng người dùng trở lại trang Profile.
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


@app.route('/my-lists/<int:list_id>/rename-ajax', methods=['POST'])
# @login_required # Nếu bạn có decorator @login_required, hãy sử dụng nó ở đây
def rename_my_list_ajax(list_id):
    """
    Xử lý yêu cầu AJAX của người dùng để đổi tên một VocabularyList của chính họ.
    Yêu cầu này thường được gửi từ một modal trên trang chi tiết danh sách hoặc trang "My Lists".
    Chỉ chấp nhận phương thức POST và dữ liệu JSON.
    """

    # 1. Kiểm tra xem người dùng đã đăng nhập chưa.
    current_user_db_id = session.get("db_user_id")
    if not current_user_db_id:
        # Nếu chưa đăng nhập, trả về lỗi 401 Unauthorized (cho AJAX).
        return jsonify({"success": False, "message": "Vui lòng đăng nhập để đổi tên danh sách."}), 401

    # 2. Tìm VocabularyList cần đổi tên trong database dựa trên list_id từ URL.
    #    Sử dụng get_or_404 để tự động trả về lỗi 404 nếu không tìm thấy.
    #    Tuy nhiên, vì đây là AJAX và chúng ta muốn trả về JSON, nên query.get() rồi kiểm tra sẽ tốt hơn.
    list_to_rename = VocabularyList.query.get(list_id)

    # 3. Kiểm tra xem danh sách có thực sự tồn tại không.
    if not list_to_rename:
        return jsonify({"success": False, "message": "Không tìm thấy danh sách để đổi tên."}), 404  # Not Found

    # 4. QUAN TRỌNG: Kiểm tra quyền sở hữu.
    #    Đảm bảo rằng danh sách này thực sự thuộc về người dùng hiện tại đang đăng nhập.
    if list_to_rename.user_id != current_user_db_id:
        # Nếu không phải, người dùng không có quyền sửa danh sách này. Trả về lỗi 403 Forbidden.
        return jsonify({"success": False, "message": "Bạn không có quyền sửa danh sách này."}), 403

    # 5. Lấy dữ liệu JSON từ request (chứa tên mới của danh sách).
    data = request.get_json()
    if not data or 'new_list_name' not in data:
        # Nếu không có dữ liệu hoặc thiếu key 'new_list_name', trả về lỗi 400 Bad Request.
        return jsonify({"success": False, "message": "Tên danh sách mới không được cung cấp trong yêu cầu."}), 400

    new_name = data.get('new_list_name', '').strip()  # Lấy tên mới và loại bỏ khoảng trắng thừa.

    # 6. Validate tên mới.
    if not new_name:
        return jsonify({"success": False, "message": "Tên danh sách mới không được để trống."}), 400

    # Ví dụ: giới hạn độ dài tên list (nên đồng bộ với định nghĩa trong model VocabularyList)
    if len(new_name) > 150:
        return jsonify({"success": False, "message": "Tên danh sách quá dài (tối đa 150 ký tự)."}), 400

    # 7. Kiểm tra xem tên mới có trùng với một list khác của cùng người dùng này không.
    #    Điều này giúp tránh việc một người dùng có nhiều danh sách với cùng một tên.
    existing_list_with_new_name = VocabularyList.query.filter(
        VocabularyList.user_id == current_user_db_id,  # Chỉ kiểm tra trong các list của user hiện tại
        VocabularyList.name == new_name,  # Tên mới có trùng không
        VocabularyList.id != list_id  # Loại trừ chính list đang được đổi tên ra khỏi kiểm tra
    ).first()

    if existing_list_with_new_name:
        # Nếu đã có list khác cùng tên, báo lỗi.
        return jsonify({"success": False,
                        "message": f"Bạn đã có một danh sách khác với tên '{new_name}'. Vui lòng chọn tên khác."}), 400

    try:
        # 8. Cập nhật tên của đối tượng VocabularyList.
        list_to_rename.name = new_name
        db.session.commit()  # Lưu thay đổi vào database.

        # Không cần flash message ở đây vì đây là AJAX request.
        # Thông báo sẽ được xử lý bởi JavaScript ở client dựa trên JSON response.

        print(f"User {current_user_db_id} đã đổi tên list ID {list_id} thành '{new_name}'")  # Debug log

        # 9. Trả về JSON báo thành công, kèm theo tên mới.
        #    Client JavaScript có thể sử dụng 'new_name' để cập nhật UI động mà không cần reload trang.
        return jsonify({"success": True, "message": "Đổi tên danh sách thành công!", "new_name": new_name})

    except Exception as e:
        # 10. Nếu có bất kỳ lỗi nào xảy ra trong quá trình tương tác với database,
        #     hoàn tác lại các thay đổi (rollback).
        db.session.rollback()
        # Ghi log lỗi chi tiết ở server.
        print(f"Lỗi khi User {current_user_db_id} đổi tên list ID {list_id}: {e}")
        # Trả về JSON báo lỗi server.
        return jsonify({"success": False, "message": f"Lỗi server khi đổi tên danh sách: {str(e)}"}), 500


if __name__ == '__main__':
    with app.app_context():
        app.run(debug=True)
