from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

# Khởi tạo đối tượng SQLAlchemy ở đây, nhưng chưa liên kết với app Flask nào cụ thể
# App sẽ được liên kết sau trong file app.py để tránh circular import
db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'user'  # Tên bảng rõ ràng (tùy chọn nhưng tốt)
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=True)  # Tên gốc (từ Google hoặc form đăng ký)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=True)
    google_id = db.Column(db.String(100), unique=True, nullable=True)
    picture_url = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    display_name = db.Column(db.String(100), nullable=True)  # <<< TRƯỜNG MỚI: Tên hiển thị

    is_blocked = db.Column(db.Boolean, default=False, nullable=True)
    # Quan hệ: Một User có nhiều VocabularyList
    vocabulary_lists = db.relationship('VocabularyList', backref='user', lazy=True, cascade="all, delete-orphan")

    # Quan hệ: Một User có nhiều VocabularyEntry (nếu muốn truy vấn trực tiếp các từ của user)
    # vocabulary_entries = db.relationship('VocabularyEntry', backref='user', lazy=True) # Cân nhắc có cần không nếu đã có qua list

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password) if self.password_hash else False

    def __repr__(self):
        return f'<User {self.email}>'


class VocabularyList(db.Model):
    __tablename__ = 'vocabulary_list'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)  # Tên danh sách người dùng đặt
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # Khóa ngoại liên kết đến bảng User

    # Quan hệ: Một VocabularyList có nhiều VocabularyEntry
    # 'cascade="all, delete-orphan"' nghĩa là khi xóa một list, tất cả entry trong list đó cũng bị xóa
    entries = db.relationship('VocabularyEntry', backref='vocabulary_list', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<VocabularyList {self.name} by User {self.user_id}>'


# --- MODEL MỚI: VocabularyEntry ---
class VocabularyEntry(db.Model):
    __tablename__ = 'vocabulary_entry'
    id = db.Column(db.Integer, primary_key=True)
    original_word = db.Column(db.String(200), nullable=False)
    word_type = db.Column(db.String(50), nullable=True)  # Loại từ (noun, verb, adj, ...)
    ipa = db.Column(db.String(100), nullable=True)
    definition_en = db.Column(db.Text, nullable=True)  # Định nghĩa/Giải thích tiếng Anh
    definition_vi = db.Column(db.Text, nullable=True)  # Định nghĩa/Giải thích tiếng Việt
    example_en = db.Column(db.Text, nullable=True)  # Câu ví dụ tiếng Anh
    # example_vi = db.Column(db.Text, nullable=True) # Nghĩa câu ví dụ tiếng Việt (nếu sau này có)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    list_id = db.Column(db.Integer, db.ForeignKey('vocabulary_list.id'),
                        nullable=False)  # Khóa ngoại liên kết đến VocabularyList
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'),
                        nullable=False)  # Khóa ngoại liên kết đến User (để tiện truy vấn)

    def __repr__(self):
        return f'<VocabularyEntry {self.original_word} in List {self.list_id}>'




class APILog(db.Model):
    __tablename__ = 'api_log'
    id = db.Column(db.Integer, primary_key=True)
    api_name = db.Column(db.String(100), nullable=False) # Tên API được gọi, ví dụ: 'deep_translator', 'dictionary_api'
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    success = db.Column(db.Boolean, default=True, nullable=False) # True nếu gọi thành công, False nếu có lỗi
    status_code = db.Column(db.Integer, nullable=True) # Mã trạng thái HTTP từ API (nếu có)
    error_message = db.Column(db.Text, nullable=True) # Thông báo lỗi (nếu có)
    request_details = db.Column(db.Text, nullable=True) # Chi tiết yêu cầu (ví dụ: từ cần dịch/tra cứu)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) # User nào gây ra lời gọi API (nếu có)

    # Quan hệ ngược lại với User (tùy chọn, nếu muốn dễ dàng xem log của user)
    # logged_by_user = db.relationship('User', backref=db.backref('api_logs', lazy='dynamic'))


    def __repr__(self):
        return f'<APILog {self.api_name} at {self.timestamp} Success: {self.success}>'
