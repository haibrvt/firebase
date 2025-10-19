import requests
import json
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
from firebase_admin import exceptions as firebase_exceptions
import time 
import pytz 

# --- Cấu hình API Myfxbook ---
MY_EMAIL = "hai12b3@gmail.com" 
MY_PASSWORD = "Hadeshai5"        
LOGIN_API = f"https://www.myfxbook.com/api/login.json?email={MY_EMAIL}&password={MY_PASSWORD}"
GET_ACCOUNTS_API_BASE = "https://www.myfxbook.com/api/get-my-accounts.json"
GET_OPEN_TRADES_API_BASE = "https://www.myfxbook.com/api/get-open-trades.json"

# --- Cấu hình Firebase ---
SERVICE_ACCOUNT_FILE = 'datafx-45432-firebase-adminsdk-fbsvc-3132a63c50.json' 
COLLECTION_NAME = 'myfxbook_snapshots'      
OPEN_TRADES_SUMMARY_COLLECTION = 'myfxbook_trades_summary' 
SESSION_DOC_ID = 'current_session'          
SUMMARY_DOC_PREFIX = 'summary_snapshot'     

# 🆕 Cấu hình Múi Giờ Việt Nam (Asia/Ho_Chi_Minh = UTC+7)
VN_TIMEZONE = pytz.timezone('Asia/Ho_Chi_Minh')


# --- Khởi tạo Firebase ---
def initialize_firebase():
    """Khởi tạo Firebase Admin SDK và trả về client db."""
    try:
        if not firebase_admin._apps:
            cred = credentials.Certificate(SERVICE_ACCOUNT_FILE)
            firebase_admin.initialize_app(cred)
        print("✅ Kết nối Firebase thành công.")
        return firestore.client()
    except firebase_exceptions.FirebaseError as fe:
        print(f"❌ LỖI FIREBASE CỤ THỂ: Không thể khởi tạo. Vui lòng kiểm tra file khóa: {fe}")
        raise
    except Exception as e:
        print(f"❌ LỖI KHỞI TẠO CHUNG: {e}")
        raise

# --- Hàm Hỗ Trợ (Giữ nguyên) ---
def get_session_from_db(db):
    if not db: return None
    try:
        doc_ref = db.collection('settings').document(SESSION_DOC_ID)
        doc = doc_ref.get()
        if doc.exists:
            session = doc.to_dict().get('session_id')
            if session and len(session) > 10: 
                print(f"✅ Đã tìm thấy Session ID cũ trong DB: **{session[:8]}...**")
                return session
            else:
                print("⚠️ Session ID cũ trong DB không hợp lệ hoặc không có.")
    except Exception as e:
        print(f"⚠️ Lỗi khi đọc session cũ từ DB: {e}")
    return None

def save_session_to_db(db, new_session_id, current_timestamp_str):
    if not db: return
    try:
        doc_ref = db.collection('settings').document(SESSION_DOC_ID)
        doc_ref.set({
            'session_id': new_session_id,
            'last_updated': current_timestamp_str
        })
        print("✅ Đã lưu Session ID mới vào DB thành công.")
    except Exception as e:
        print(f"⚠️ Lỗi khi lưu session mới vào DB: {e}")

def fetch_data(api_url, current_session_id, account_id=None): 
    full_url = f"{api_url}?session={current_session_id}"
    if account_id:
        full_url += f"&id={account_id}"
    try:
        response = requests.get(full_url, timeout=30)
        if response.status_code != 200:
            print(f"❌ Lỗi HTTP: Status Code {response.status_code} khi gọi {api_url}")
            response.raise_for_status()
        data = response.json()
        if data.get('error') not in [False, None]: 
            print(f"❌ API báo lỗi khi gọi {api_url}. Lỗi: {data['error']}")
            return None 
        return data 
    except requests.exceptions.RequestException as e:
        print(f"❌ LỖI KẾT NỐI API Myfxbook ({api_url}): {e}")
        return None
    except json.JSONDecodeError:
        print(f"❌ LỖI PHÂN TÍCH JSON: Phản hồi không phải JSON hợp lệ từ {api_url}.")
        return None

def fetch_and_get_open_trades_summary(current_session_id, account_id):
    response_data = fetch_data(GET_OPEN_TRADES_API_BASE, current_session_id, account_id=account_id)
    if not response_data:
        print(f"    ❌ Không lấy được dữ liệu lệnh mở cho ID {account_id}.")
        return None 
    open_trades = response_data.get('openTrades')
    num_trades = len(open_trades) if isinstance(open_trades, list) else 0
    print(f"    ✅ Thành công. Tìm thấy **{num_trades}** lệnh đang mở.")
    return {
        'account_id': account_id,
        'open_trades_count': num_trades
    }
        
def perform_login():
    try:
        response = requests.get(LOGIN_API, timeout=30) 
        response.raise_for_status()
        data = response.json()
        is_success = data.get('session') and data.get('error') in [False, None]
        if is_success:
            session_id = data['session']
            print(f"✅ Đăng nhập thành công! Session ID mới: **{session_id[:8]}...**")
            return session_id
        else:
            print(f"❌ Đăng nhập thất bại. Phản hồi API: {json.dumps(data, indent=4)}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"❌ LỖI KẾT NỐI API Myfxbook (Đăng nhập): {e}")
        return None
    except json.JSONDecodeError:
        print(f"❌ LỖI PHÂN TÍCH JSON: Phản hồi đăng nhập không hợp lệ.")
        return None

# --- Hàm Quy trình Chính (Thực thi một lần - Đã sửa múi giờ) ---

def run_data_collection():
    """Chứa toàn bộ logic thu thập và lưu dữ liệu chính."""
    
    # 🇻🇳 LẤY THỜI GIAN HIỆN TẠI VỚI MÚI GIỜ VIỆT NAM (CÁCH CHUẨN MỰC HƠN)
    # 1. Lấy thời gian hiện tại ở UTC (zone-aware)
    utc_now = datetime.now(pytz.utc)
    # 2. Chuyển đổi sang múi giờ Việt Nam (UTC+7)
    timestamp = utc_now.astimezone(VN_TIMEZONE) 
    
    timestamp_str = timestamp.isoformat()
    
    session_id = None
    all_accounts_data = None
    open_trades_summary_list = [] 
    db = None

    print("\n" + "=" * 50)
    print(f"🎬 BẮT ĐẦU VÒNG CHẠY GitHub Action lúc (VN Time): {timestamp.strftime('%Y-%m-%d %H:%M:%S %Z%z')}")
    print("=" * 50)
    
    try:
        db = initialize_firebase()
    except Exception:
        print("❌ Lỗi nghiêm trọng: Không có kết nối Firebase. Bỏ qua lần chạy này.")
        return

    # 1. Thử lấy Session ID cũ
    session_id = get_session_from_db(db)

    # 2. Đăng nhập hoặc sử dụng Session cũ
    MAX_ATTEMPTS = 2
    attempt = 0
    is_success = False

    while attempt < MAX_ATTEMPTS and not is_success:
        attempt += 1
        
        if session_id:
            print(f"2.{attempt}. Đang thử lấy dữ liệu với Session cũ...")
            accounts_response_data = fetch_data(GET_ACCOUNTS_API_BASE, session_id)
            
            if accounts_response_data:
                all_accounts_data = accounts_response_data
                print(f"✅ Lấy dữ liệu tài khoản tổng quan thành công bằng Session cũ! Tiếp tục.")
                is_success = True
                break 
            else:
                session_id = None 
        
        if not is_success:
            if attempt == 1:
                print("2.1. Không có Session ID cũ/hợp lệ. Tiến hành Đăng nhập...")
            new_session = perform_login()
            if new_session:
                session_id = new_session
                save_session_to_db(db, session_id, timestamp_str) 
            else:
                print("❌ Đăng nhập thất bại và không thể lấy Session ID mới. Thoát.")
                break 

    # 3. Lưu dữ liệu Tài khoản Tổng quan
    print("-" * 40)
    if all_accounts_data and all_accounts_data.get('accounts'):
        num_accounts = len(all_accounts_data['accounts'])
        print(f"3. Đang Lưu dữ liệu tổng quan của {num_accounts} tài khoản vào Firestore...")
        snapshot_document = {
            # Biến timestamp_str đã được định dạng chuẩn ISO 8601 (có kèm múi giờ)
            'timestamp': timestamp_str, 
            'source_api': 'myfxbook_get_my_accounts',
            'accounts_count': num_accounts,
            'data': all_accounts_data 
        }
        try:
            doc_id = f'snapshot-{timestamp.strftime("%Y%m%d%H%M%S")}'
            doc_ref = db.collection(COLLECTION_NAME).document(doc_id)
            doc_ref.set(snapshot_document)
            print("✅ Dữ liệu tổng quan đã được lưu thành công vào Firestore với ID:", doc_id)
        except Exception as e:
            print(f"❌ Lỗi khi lưu vào Firestore: {e}")
    else:
        print("⚠️ Bỏ qua bước Lưu Dữ liệu Tổng quan: Không có dữ liệu tài khoản hợp lệ để lưu.")

    # 4. Lấy dữ liệu Lệnh đang mở (Tạo mảng tóm tắt)
    print("-" * 40)
    if all_accounts_data and all_accounts_data.get('accounts') and session_id:
        accounts_to_fetch = all_accounts_data['accounts']
        print(f"4. Bắt đầu lấy **số lượng lệnh đang mở** cho {len(accounts_to_fetch)} tài khoản...")
        for account in accounts_to_fetch:
            account_id = account.get('id')
            if account_id:
                summary_item = fetch_and_get_open_trades_summary(session_id, account_id)
                if summary_item:
                    open_trades_summary_list.append(summary_item) 
                time.sleep(1) 
            else:
                print("    ⚠️ Bỏ qua một tài khoản: Không tìm thấy ID.")
        print("✅ Hoàn tất quá trình lấy số lệnh đang mở và tạo mảng tóm tắt.")
    else:
        print("⚠️ Bỏ qua bước Lấy Lệnh đang mở: Không có dữ liệu tài khoản hoặc Session ID.")

    # 5. LƯU MẢNG JSON TÓM TẮT LÊN FIRESTORE
    print("-" * 40)
    if open_trades_summary_list:
        print(f"5. Đang Lưu **Mảng Tóm Tắt** của {len(open_trades_summary_list)} tài khoản vào Firestore...")
        summary_document = {
            'timestamp': timestamp_str,
            'source_api': 'myfxbook_open_trades_summary',
            'accounts_count': len(open_trades_summary_list),
            'data': open_trades_summary_list
        }
        try:
            doc_id = f'{SUMMARY_DOC_PREFIX}-{timestamp.strftime("%Y%m%d%H%M%S")}'
            doc_ref = db.collection(OPEN_TRADES_SUMMARY_COLLECTION).document(doc_id)
            doc_ref.set(summary_document)
            print(f"✅ Đã lưu Mảng Tóm Tắt thành công vào Collection '{OPEN_TRADES_SUMMARY_COLLECTION}' với ID: {doc_id}")
        except Exception as e:
            print(f"❌ Lỗi khi lưu Mảng Tóm Tắt vào Firestore: {e}")
    else:
        print("⚠️ Bỏ qua bước Lưu Mảng Tóm Tắt: Danh sách rỗng.")

    print("-" * 40)
    print("🏁 Quy trình cho vòng chạy này hoàn tất.")


# --- THỰC THI CHÍNH ---
if __name__ == '__main__':
    print("\n" + "#" * 60)
    print("🚀 Bắt đầu Chế độ Chạy Một Lần theo Lịch trình (Tương thích GitHub Actions).")
    print("#" * 60)
    try:
        run_data_collection() 
    except Exception as e:
        print(f"\n‼️ FATAL ERROR: Lỗi không xác định xảy ra ở cấp độ ngoài cùng: {e}")
    print("\n" + "~" * 60)
    print("🏁 Tập lệnh đã hoàn thành và sẽ kết thúc.")
    print("~" * 60)
