# --- Standard Library Imports ---
from datetime import datetime  # Để làm việc với ngày giờ, ví dụ: default=datetime.utcnow

# --- Flask Extensions ---
from flask_sqlalchemy import SQLAlchemy  # ORM để tương tác với database
from flask_wtf import FlaskForm  # Lớp cơ sở để tạo form trong Flask-WTF

# --- Werkzeug (Thư viện nền tảng của Flask, dùng cho hashing mật khẩu) ---
from werkzeug.security import generate_password_hash, check_password_hash

# --- WTForms Fields and Validators (Các trường và bộ kiểm tra dữ liệu cho form) ---
from wtforms import StringField, PasswordField, BooleanField, SubmitField  # Các loại trường input
from wtforms.validators import DataRequired, Email, Length, EqualTo  # Các bộ kiểm tra dữ liệu

# Khởi tạo đối tượng SQLAlchemy ở đây.
# Nó chưa được liên kết với một ứng dụng Flask cụ thể nào.
# Việc liên kết (db.init_app(app)) sẽ được thực hiện trong file app.py chính
# để tránh vấn đề circular import (import vòng tròn).
db = SQLAlchemy()


# === MODEL DEFINITIONS ===

class User(db.Model):
    """
    Định nghĩa model User, đại diện cho bảng 'user' trong database.
    Lưu trữ thông tin người dùng.
    """
    __tablename__ = 'user'  # Tên bảng trong database (tùy chọn nhưng nên có để rõ ràng)

    # --- Các cột của bảng User ---
    id = db.Column(db.Integer, primary_key=True)  # Khóa chính, tự động tăng
    name = db.Column(db.String(100), nullable=True)  # Tên gốc của người dùng (từ Google hoặc form đăng ký)
    # nullable=True: cho phép giá trị NULL (ví dụ nếu chỉ có email)
    email = db.Column(db.String(120), unique=True, nullable=False)  # Email, bắt buộc và không trùng lặp
    password_hash = db.Column(db.String(256), nullable=True)  # Hash của mật khẩu (nếu đăng ký bằng form)
    # nullable=True: cho phép NULL (nếu đăng nhập bằng Google và chưa đặt mật khẩu hệ thống)
    google_id = db.Column(db.String(100), unique=True,
                          nullable=True)  # ID người dùng từ Google (nếu đăng nhập bằng Google)
    picture_url = db.Column(db.String(255), nullable=True)  # URL ảnh đại diện (từ Google hoặc sau này cho phép upload)
    created_at = db.Column(db.DateTime,
                           default=datetime.utcnow)  # Thời điểm tài khoản được tạo, mặc định là thời gian UTC hiện tại
    is_admin = db.Column(db.Boolean, default=False, nullable=False)  # Cờ xác định người dùng có phải Admin không
    display_name = db.Column(db.String(100), nullable=True)  # Tên hiển thị tùy chỉnh của người dùng
    is_blocked = db.Column(db.Boolean, default=False, nullable=False)  # Cờ xác định tài khoản có bị Admin chặn không
    # Sửa lại nullable=False nếu bạn muốn nó luôn có giá trị (mặc định là False)

    # --- Mối quan hệ (Relationships) ---
    # Một User có thể tạo nhiều VocabularyList.
    # backref='user': Tạo một thuộc tính 'user' trong model VocabularyList để truy cập ngược lại User sở hữu.
    # lazy=True: Các VocabularyList liên quan sẽ được tải khi cần thiết, không tải ngay khi query User.
    # cascade="all, delete-orphan":
    #   - 'all': Các thao tác (như delete) trên User sẽ được áp dụng cho các VocabularyList liên quan.
    #   - 'delete-orphan': Nếu một VocabularyList không còn được liên kết với User nào, nó sẽ bị xóa.
    vocabulary_lists = db.relationship('VocabularyList', backref='user', lazy=True, cascade="all, delete-orphan")

    # (Tùy chọn) Một User có thể có nhiều VocabularyEntry trực tiếp (nếu bạn muốn truy vấn tất cả các từ của user
    # mà không cần qua VocabularyList). Tuy nhiên, hiện tại mỗi VocabularyEntry đã có user_id, nên có thể không cần relationship này.
    # vocabulary_entries = db.relationship('VocabularyEntry', backref='user_owner', lazy=True, cascade="all, delete-orphan") 
    # Nếu dùng, cần đổi tên backref để không trùng với backref của VocabularyList.

    # --- Các phương thức của Model User ---
    def set_password(self, password):
        """Tạo hash cho mật khẩu và lưu vào password_hash."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Kiểm tra mật khẩu người dùng nhập với password_hash đã lưu."""
        # Chỉ kiểm tra nếu password_hash đã được đặt
        return check_password_hash(self.password_hash, password) if self.password_hash else False

    def __repr__(self):
        """Biểu diễn đối tượng User dưới dạng chuỗi (hữu ích khi debug)."""
        return f'<User {self.id} - {self.email}>'


class VocabularyList(db.Model):
    """
    Định nghĩa model VocabularyList, đại diện cho bảng 'vocabulary_list'.
    Mỗi đối tượng là một danh sách từ vựng do người dùng tạo.
    """
    __tablename__ = 'vocabulary_list'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)  # Tên của danh sách từ vựng, bắt buộc
    created_at = db.Column(db.DateTime, default=datetime.utcnow)  # Thời điểm danh sách được tạo

    # Khóa ngoại user_id: Liên kết danh sách này với một User cụ thể.
    # db.ForeignKey('user.id') trỏ đến cột 'id' của bảng 'user'.
    # nullable=False: Mỗi danh sách phải thuộc về một User.
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Mối quan hệ: Một VocabularyList có thể chứa nhiều VocabularyEntry.
    # backref='vocabulary_list': Tạo một thuộc tính 'vocabulary_list' trong model VocabularyEntry 
    #                            để truy cập ngược lại VocabularyList chứa nó.
    # lazy=True: Các VocabularyEntry liên quan sẽ được tải khi cần.
    # cascade="all, delete-orphan": Khi một VocabularyList bị xóa, tất cả các VocabularyEntry
    #                               trong nó cũng sẽ tự động bị xóa.
    entries = db.relationship('VocabularyEntry', backref='vocabulary_list', lazy='dynamic',
                              cascade="all, delete-orphan")

    # lazy='dynamic' cho phép bạn thực hiện các truy vấn tiếp theo trên 'entries' (ví dụ: .filter_by(), .count())

    def __repr__(self):
        return f'<VocabularyList {self.id} - "{self.name}" by User ID {self.user_id}>'


class VocabularyEntry(db.Model):
    """
    Định nghĩa model VocabularyEntry, đại diện cho bảng 'vocabulary_entry'.
    Mỗi đối tượng là một mục từ vựng cụ thể.
    """
    __tablename__ = 'vocabulary_entry'
    id = db.Column(db.Integer, primary_key=True)
    original_word = db.Column(db.String(200), nullable=False)  # Từ gốc tiếng Anh, bắt buộc
    word_type = db.Column(db.String(50), nullable=True)  # Loại từ (noun, verb, adj, ...)
    ipa = db.Column(db.String(100), nullable=True)  # Phiên âm IPA
    definition_en = db.Column(db.Text, nullable=True)  # Giải thích nghĩa bằng tiếng Anh
    definition_vi = db.Column(db.Text, nullable=True)  # Giải thích nghĩa bằng tiếng Việt
    example_en = db.Column(db.Text, nullable=True)  # Câu ví dụ tiếng Anh
    # example_vi = db.Column(db.Text, nullable=True)         # (Tùy chọn) Nghĩa câu ví dụ tiếng Việt
    added_at = db.Column(db.DateTime, default=datetime.utcnow)  # Thời điểm mục từ được thêm vào

    # Khóa ngoại list_id: Liên kết mục từ này với một VocabularyList cụ thể.
    list_id = db.Column(db.Integer, db.ForeignKey('vocabulary_list.id'), nullable=False)

    # Khóa ngoại user_id: Liên kết trực tiếp mục từ này với người dùng đã tạo ra nó.
    # Điều này giúp dễ dàng truy vấn tất cả các từ của một user mà không cần join qua VocabularyList,
    # và cũng quan trọng cho việc kiểm tra quyền sở hữu khi sửa/xóa entry.
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    def __repr__(self):
        return f'<VocabularyEntry {self.id} - "{self.original_word}" in List ID {self.list_id}>'


class APILog(db.Model):
    """
    Định nghĩa model APILog, đại diện cho bảng 'api_log'.
    Lưu trữ thông tin về các lần ứng dụng gọi đến API bên ngoài.
    """
    __tablename__ = 'api_log'
    id = db.Column(db.Integer, primary_key=True)
    api_name = db.Column(db.String(100),
                         nullable=False)  # Tên của API được gọi (ví dụ: 'deep_translator', 'dictionary_api')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)  # Thời điểm gọi API
    success = db.Column(db.Boolean, default=True, nullable=False)  # Trạng thái thành công (True) hay thất bại (False)
    status_code = db.Column(db.Integer, nullable=True)  # Mã trạng thái HTTP từ API (nếu có, ví dụ: 200, 404, 500)
    error_message = db.Column(db.Text, nullable=True)  # Thông báo lỗi chi tiết (nếu có)
    request_details = db.Column(db.Text, nullable=True)  # Một phần thông tin của request (ví dụ: từ cần dịch)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'),
                        nullable=True)  # ID của người dùng gây ra lời gọi API (nếu có)

    # nullable=True vì có thể API được gọi bởi hệ thống.

    # (Tùy chọn) Quan hệ ngược lại với User để dễ dàng xem log của một user cụ thể.
    # logged_by_user = db.relationship('User', backref=db.backref('api_logs', lazy='dynamic'))

    def __repr__(self):
        return f'<APILog ID {self.id} - API: {self.api_name} at {self.timestamp} Success: {self.success}>'


# === FORM DEFINITIONS (Sử dụng Flask-WTF) ===

class RegistrationForm(FlaskForm):
    """
    Định nghĩa form đăng ký người dùng mới.
    Sử dụng các trường và validators của WTForms.
    Tự động xử lý CSRF protection khi được dùng trong template với {{ form.hidden_tag() }}.
    """
    name = StringField('Họ và Tên',
                       validators=[DataRequired(message="Vui lòng nhập họ và tên.")])
    email = StringField('Địa chỉ Email',
                        validators=[DataRequired(message="Vui lòng nhập địa chỉ email."),
                                    Email(message="Địa chỉ email không hợp lệ.")])
    password = PasswordField('Mật khẩu',
                             validators=[DataRequired(message="Vui lòng nhập mật khẩu."),
                                         Length(min=6, message="Mật khẩu phải có ít nhất 6 ký tự.")])
    confirm_password = PasswordField('Xác nhận Mật khẩu',
                                     validators=[DataRequired(message="Vui lòng xác nhận mật khẩu."),
                                                 EqualTo('password', message='Mật khẩu xác nhận không khớp.')])
    agree_terms = BooleanField(
        'Tôi đã đọc và đồng ý với các <a href="{{ url_for(\'terms_of_service_page\') }}" target="_blank" class="text-orange-600 hover:underline">Điều khoản Dịch vụ</a> và <a href="{{ url_for(\'privacy_policy_page\') }}" target="_blank" class="text-orange-600 hover:underline">Chính sách Bảo mật</a> của G-Easy English.',
        validators=[DataRequired(message="Bạn phải đồng ý với các điều khoản và chính sách để đăng ký.")]
    )
    submit = SubmitField('Đăng ký')
