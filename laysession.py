import requests
import json
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
from firebase_admin import exceptions as firebase_exceptions

# --- Cấu hình API Myfxbook ---
# ⚠️ THAY THẾ BẰNG THÔNG TIN THỰC TẾ CỦA BẠN
MY_EMAIL = "hai12b3@gmail.com"  
MY_PASSWORD = "Hadeshai5"        
LOGIN_API = f"https://www.myfxbook.com/api/login.json?email={MY_EMAIL}&password={MY_PASSWORD}"
GET_ACCOUNTS_API_BASE = "https://www.myfxbook.com/api/get-my-accounts.json"
GET_OPEN_TRADES_API_BASE = "https://www.myfxbook.com/api/get-open-trades.json"

# --- Cấu hình Firebase ---
SERVICE_ACCOUNT_FILE = 'datafx-45432-firebase-adminsdk-fbsvc-3132a63c50.json' 
COLLECTION_NAME = 'myfxbook_snapshots'              # Collection lưu dữ liệu tài khoản tổng quan
OPEN_TRADES_SUMMARY_COLLECTION = 'myfxbook_trades_summary' # Collection lưu mảng tóm tắt lệnh mở
SESSION_DOC_ID = 'current_session'                  # ID document cho bản latest/dashboard
SUMMARY_DOC_PREFIX = 'summary_snapshot'             # Tiền tố cho document lưu mảng tóm tắt lịch sử

def initialize_firebase():
    """Khởi tạo Firebase Admin SDK."""
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

def get_session_id():
    """Lấy Session ID bằng cách đăng nhập."""
    print("\n⏳ Đang đăng nhập để lấy Session ID...")
    try:
        response = requests.get(LOGIN_API, timeout=30) 
        response.raise_for_status() # Báo lỗi HTTP nếu có
        data = response.json()
        
        is_success = data.get('session') and (data.get('error') is False or data.get('error') is None)
        
        if is_success:
            session_id = data['session']
            print(f"✅ Đăng nhập thành công! Session ID: **{session_id[:10]}...**")
            return session_id
        else:
            print("❌ Đăng nhập thất bại. Mã phản hồi JSON (Kiểm tra Email/Password):")
            print(json.dumps(data, indent=4))
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"❌ LỖI KẾT NỐI API Myfxbook (Đăng nhập): {e}")
        return None
    except json.JSONDecodeError:
        print(f"❌ LỖI PHÂN TÍCH JSON: Phản hồi không phải JSON hợp lệ. Nội dung: {response.text[:100]}...")
        return None


def fetch_data(api_url, session_id, **params): 
    """Lấy dữ liệu từ API Myfxbook."""
    full_url = f"{api_url}?session={session_id}"
    
    if params:
        for key, value in params.items():
            full_url += f"&{key}={value}"
    
    # ℹ️ In ra URL để debug (tùy chọn)
    # print(f"    -> Gọi API: {full_url}")

    try:
        response = requests.get(full_url, timeout=30)
        
        if response.status_code != 200:
            print(f"❌ Lỗi HTTP: Status Code {response.status_code} khi gọi {api_url}")
            response.raise_for_status()
            
        data = response.json()
        
        if data.get('error') and data.get('error') is not False:
            print(f"❌ API báo lỗi khi gọi {api_url}: {data['error']}")
            return None 
            
        return data 
        
    except requests.exceptions.RequestException as e:
        print(f"❌ LỖI KẾT NỐI API Myfxbook ({api_url}): {e}")
        return None
    except json.JSONDecodeError:
        print(f"❌ LỖI PHÂN TÍCH JSON: Phản hồi không phải JSON hợp lệ từ {api_url}.")
        return None

def find_account_list(data):
    """Tìm mảng dữ liệu tài khoản trong phản hồi JSON thô."""
    if not isinstance(data, dict):
        return []
    
    # Myfxbook thường dùng key 'accounts' hoặc 'openTrades'
    if 'accounts' in data and isinstance(data['accounts'], list):
        return data['accounts']
    
    # Trường hợp chung: tìm list không rỗng chứa dict với các key đặc trưng
    for key, value in data.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            account_keys = {'id', 'name', 'balance', 'equity'} 
            if account_keys.issubset(value[0].keys()):
                 return value
                 
    return []

def save_snapshot_to_firestore(db, raw_data):
    """
    Lưu toàn bộ dữ liệu snapshot thô vào Firestore.
    Lưu 2 bản: Latest (Dashboard) và History (Timestamp ID).
    """
    accounts_list = find_account_list(raw_data)
    num_accounts = len(accounts_list) if accounts_list else 0
    
    if num_accounts == 0:
        print("❌ Lỗi: Không tìm thấy danh sách tài khoản hợp lệ trong phản hồi API.")
        return

    try:
        current_time = datetime.now()
        timestamp_str = current_time.isoformat()
        
        # ⚠️ Sửa đổi để lưu TOÀN BỘ phản hồi thô vào trường 'data'
        document_data = {
            'timestamp': timestamp_str,
            'source_api': 'myfxbook_get_my_accounts', # Thêm trường này giống laysession
            'accounts_count': num_accounts,           # Thêm trường này giống laysession
            'data': raw_data,                         # Lưu phản hồi thô (chứa khóa 'accounts')
            'success': raw_data.get('error') is False
        }
        
        # 1. Lưu vào document dashboard (latest)
        doc_ref_latest = db.collection(COLLECTION_NAME).document(SESSION_DOC_ID)
        doc_ref_latest.set(document_data)
        
        # 2. Lưu vào history
        history_doc_id = f'snapshot-{current_time.strftime("%Y%m%d%H%M%S")}' # Giống định dạng laysession
        history_doc_ref = db.collection(COLLECTION_NAME).document(history_doc_id)
        history_doc_ref.set(document_data)
        
        print(f"✅ Dữ liệu tổng quan của **{num_accounts}** tài khoản đã được lưu thành công vào Firestore.")
        print(f"   ID Dashboard: {SESSION_DOC_ID}, ID History: {history_doc_id}")
    except Exception as e:
        print(f"❌ Lỗi khi lưu Snapshot vào Firestore: {e}")

def save_open_trades_summary(db, open_trades_data):
    """
    Tạo mảng tóm tắt số lệnh đang mở và lưu vào document lịch sử mới.
    """
    # API get-open-trades.json trả về JSON có key 'accounts' chứa mảng
    accounts_with_trades_list = open_trades_data.get('accounts', []) 
    
    open_trades_summary_list = []
    
    if accounts_with_trades_list:
        for acc in accounts_with_trades_list:
            account_id_long = acc.get('id') 
            trades = acc.get('openTrades', []) # API get-open-trades sử dụng key 'openTrades'
            
            if account_id_long:
                # Tạo mục tóm tắt
                summary_item = {
                    'account_id': account_id_long, 
                    'open_trades_count': len(trades)
                }
                open_trades_summary_list.append(summary_item)

        
        if open_trades_summary_list:
            try:
                current_time = datetime.now()
                timestamp_str = current_time.isoformat()
                
                summary_document = {
                    'timestamp': timestamp_str,
                    'source_api': 'myfxbook_open_trades_summary', # Giống laysession
                    'accounts_count': len(open_trades_summary_list),
                    'data': open_trades_summary_list,             # Đây là mảng JSON tóm tắt
                    'success': open_trades_data.get('error') is False
                }
                
                # Sử dụng timestamp làm ID document lịch sử với tiền tố
                doc_id = f'{SUMMARY_DOC_PREFIX}-{current_time.strftime("%Y%m%d%H%M%S")}'
                doc_ref = db.collection(OPEN_TRADES_SUMMARY_COLLECTION).document(doc_id)
                doc_ref.set(summary_document)
                
                print("✅ Mảng JSON Tóm Tắt Lệnh Đang Mở Đã Tạo:")
                print(json.dumps(open_trades_summary_list, indent=4))
                print(f"✅ Đã lưu Mảng Tóm Tắt thành công vào Collection '{OPEN_TRADES_SUMMARY_COLLECTION}' với ID: {doc_id}")
                
            except Exception as e:
                print(f"❌ Lỗi khi lưu Mảng Tóm Tắt vào Firestore: {e}")
    else:
        print("⚠️ Bỏ qua bước Lưu Mảng Tóm Tắt: Không có dữ liệu lệnh đang mở hợp lệ.")


def run_data_collection():
    """Thực hiện toàn bộ quy trình thu thập và lưu dữ liệu."""
    
    account_ids_list = []
    
    print("\n" + "=" * 50)
    print(f"🎬 BẮT ĐẦU VÒNG CHẠY lúc: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    try:
        # 1. Khởi tạo Firebase
        db = initialize_firebase()
        
        # 2. Đăng nhập để lấy Session ID
        session_id = get_session_id()
        if not session_id:
            print("❌ Không có Session ID, dừng quy trình.")
            return

        # 3. Lấy dữ liệu Snapshot tài khoản
        print("-" * 40)
        print("⏳ Đang lấy dữ liệu Snapshot Tài khoản...")
        account_snapshot_data = fetch_data(GET_ACCOUNTS_API_BASE, session_id) 
        
        if account_snapshot_data:
            # Lưu dữ liệu Snapshot
            save_snapshot_to_firestore(db, account_snapshot_data)
                
            # TRÍCH XUẤT TẤT CẢ ACCOUNT ID cho bước tiếp theo
            accounts_list = find_account_list(account_snapshot_data)
            account_ids_list = [
                str(acc.get('id')) for acc in accounts_list
                if acc.get('id') is not None
            ]
            
            if not account_ids_list:
                print("⚠️ Không tìm thấy bất kỳ ID tài khoản nào để lấy lệnh đang mở.")
                return

        else:
             print("❌ Lỗi khi lấy dữ liệu Snapshot Tài khoản. Bỏ qua các bước tiếp theo.")
             return

        # 4. Lấy dữ liệu Lệnh Đang Mở (Open Trades)
        print("-" * 40)
        print("⏳ Đang lấy dữ liệu Lệnh Đang Mở...")
        
        # GẮN THAM SỐ accountIds = chuỗi các ID cách nhau bằng dấu phẩy
        account_ids_param = ",".join(account_ids_list)
        
        open_trades_data = fetch_data(
            GET_OPEN_TRADES_API_BASE, 
            session_id, 
            accountIds=account_ids_param 
        )
        
        # 5. Lưu mảng tóm tắt Lệnh Đang Mở
        print("-" * 40)
        if open_trades_data:
            save_open_trades_summary(db, open_trades_data)
        else:
            print("⚠️ Bỏ qua bước Lưu Mảng Tóm Tắt: Không lấy được dữ liệu lệnh đang mở.")

    except Exception as e:
        print(f"\n‼️ LỖI NGHIÊM TRỌNG TRONG QUÁ TRÌNH CHẠY: {e}. Vui lòng kiểm tra lại cấu hình.")

    print("\n" + "-" * 40)
    print("🏁 Quy trình cho vòng chạy này hoàn tất.")


# --- THỰC THI (MAIN EXECUTION) ---
if __name__ == '__main__':
    
    print("\n" + "#" * 60)
    print("🚀 Bắt đầu Chế độ Chạy Một Lần theo Lịch trình (GitHub Actions).")
    print("#" * 60)
    
    try:
        run_data_collection() 
    
    except Exception as e:
        print(f"\n‼️ FATAL ERROR: Lỗi không xác định xảy ra: {e}")
    
    print("\n" + "~" * 60)
    print("🏁 Tập lệnh đã hoàn thành và sẽ kết thúc.")
    print("~" * 60)
