import requests
import json
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
from firebase_admin import exceptions as firebase_exceptions
import time 

# --- Cấu hình API Myfxbook (Lấy từ 1.py) ---
MY_EMAIL = "hai12b3@gmail.com"  # Thay bằng email thực tế
MY_PASSWORD = "Hadeshai5"        # Thay bằng mật khẩu thực tế
LOGIN_API = f"https://www.myfxbook.com/api/login.json?email={MY_EMAIL}&password={MY_PASSWORD}"
GET_ACCOUNTS_API_BASE = "https://www.myfxbook.com/api/get-my-accounts.json"
GET_OPEN_TRADES_API_BASE = "https://www.myfxbook.com/api/get-open-trades.json" # API lấy lệnh đang mở (chỉ dùng để lấy số lượng, không lưu chi tiết)

# --- Cấu hình Firebase (Lấy từ laysession.py và 1.py) ---
SERVICE_ACCOUNT_FILE = 'datafx-45432-firebase-adminsdk-fbsvc-3132a63c50.json' 
COLLECTION_NAME = 'myfxbook_snapshots'      # Collection lưu dữ liệu tài khoản tổng quan
OPEN_TRADES_SUMMARY_COLLECTION = 'myfxbook_trades_summary' # Collection để lưu mảng tóm tắt
SESSION_DOC_ID = 'current_session'          # ID document để lưu/đọc Session ID
SUMMARY_DOC_PREFIX = 'summary_snapshot'     # Tiền tố cho document lưu mảng tóm tắt

# --- Khởi tạo Firebase (Lấy từ 1.py) ---

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
        # Quan trọng: Cần `raise` để dừng nếu không kết nối được Firebase
        raise
    except Exception as e:
        print(f"❌ LỖI KHỞI TẠO CHUNG: {e}")
        raise

# --- Hàm Hỗ Trợ (Lấy từ laysession.py, điều chỉnh) ---

def get_session_from_db(db):
    """Đọc Session ID gần nhất được lưu trong Firestore."""
    if not db: return None
    try:
        doc_ref = db.collection('settings').document(SESSION_DOC_ID)
        doc = doc_ref.get()
        if doc.exists:
            session = doc.to_dict().get('session_id')
            # Thêm logic kiểm tra độ dài session để đảm bảo nó hợp lệ
            if session and len(session) > 10: 
                print(f"✅ Đã tìm thấy Session ID cũ trong DB: **{session[:8]}...**")
                return session
            else:
                print("⚠️ Session ID cũ trong DB không hợp lệ hoặc không có.")
    except Exception as e:
        print(f"⚠️ Lỗi khi đọc session cũ từ DB: {e}")
    return None

def save_session_to_db(db, new_session_id, current_timestamp_str):
    """Lưu Session ID mới vào Firestore."""
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

# Lấy hàm fetch_data từ 1.py (đã loại bỏ logic params vì laysession dùng string formatting)
# Nhưng tôi sẽ dùng logic kiểm tra lỗi mạnh mẽ hơn từ 1.py
def fetch_data(api_url, current_session_id, account_id=None): 
    """Lấy dữ liệu từ API Myfxbook, dùng cho cả get-my-accounts và get-open-trades."""
    full_url = f"{api_url}?session={current_session_id}"
    
    if account_id:
        full_url += f"&id={account_id}"

    try:
        response = requests.get(full_url, timeout=30)
        
        if response.status_code != 200:
            print(f"❌ Lỗi HTTP: Status Code {response.status_code} khi gọi {api_url}")
            response.raise_for_status()
            
        data = response.json()
        
        # SỬA LỖI KIỂM TRA TỪ 1.py (data.get('error') is True)
        if data.get('error') not in [False, None]: 
            # Giả định lỗi API nếu có trường 'error' và nó không phải False/None
            print(f"❌ API báo lỗi khi gọi {api_url}. Lỗi: {data['error']}")
            return None 
            
        return data 
        
    except requests.exceptions.Timeout:
        print(f"❌ LỖI MẠNG: Gọi API {api_url} bị Timeout.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ LỖI KẾT NỐI API Myfxbook ({api_url}): {e}")
        return None
    except json.JSONDecodeError:
        # Nếu lỗi JSON, cần in ra một phần response.text để debug
        print(f"❌ LỖI PHÂN TÍCH JSON: Phản hồi không phải JSON hợp lệ từ {api_url}.")
        return None

def fetch_and_get_open_trades_summary(current_session_id, account_id):
    """
    Lấy dữ liệu lệnh đang mở cho một tài khoản cụ thể (theo logic laysession.py).
    Chỉ trả về dict {account_id, open_trades_count} nếu thành công.
    """
    print(f"    - Đang lấy số lệnh mở cho Account ID: {account_id}...")
    
    # Sử dụng hàm fetch_data đã sửa đổi
    response_data = fetch_data(GET_OPEN_TRADES_API_BASE, current_session_id, account_id=account_id)
    
    if not response_data:
        print(f"    ❌ Không lấy được dữ liệu lệnh mở cho ID {account_id}.")
        return None 

    # Dữ liệu lệnh mở nằm trong khóa 'openTrades'
    open_trades = response_data.get('openTrades')
    
    num_trades = len(open_trades) if isinstance(open_trades, list) else 0
    
    print(f"    ✅ Thành công. Tìm thấy **{num_trades}** lệnh đang mở.")

    # Chỉ trả về kết quả tóm tắt
    return {
        'account_id': account_id,
        'open_trades_count': num_trades
    }
        

def perform_login():
    """Đăng nhập để lấy Session ID (lấy logic đã sửa từ 1.py)."""
    print("⏳ Đang đăng nhập để lấy Session ID...")
    try:
        response = requests.get(LOGIN_API, timeout=30) 
        response.raise_for_status() # Báo lỗi HTTP nếu có
        data = response.json()
        
        # LOGIC KIỂM TRA THÀNH CÔNG ĐÃ ĐƯỢC SỬA 
        # Session tồn tại và không có lỗi API
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

# --- Hàm Quy trình Chính (Thực thi một lần - Tương tự laysession.py) ---

def run_data_collection():
    """Chứa toàn bộ logic thu thập và lưu dữ liệu chính."""
    
    timestamp = datetime.now()
    timestamp_str = timestamp.isoformat()
    session_id = None
    all_accounts_data = None
    open_trades_summary_list = [] 
    db = None

    print("\n" + "=" * 50)
    print(f"🎬 BẮT ĐẦU VÒNG CHẠY GitHub Action lúc: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    
    # 1. Khởi tạo Firebase
    try:
        db = initialize_firebase()
    except Exception:
        print("❌ Lỗi nghiêm trọng: Không có kết nối Firebase. Bỏ qua lần chạy này.")
        return

    # 2. Thử lấy Session ID cũ
    session_id = get_session_from_db(db)

    # 3. Vòng lặp kiểm tra và đăng nhập nếu cần
    MAX_ATTEMPTS = 2
    attempt = 0
    login_required = False
    is_success = False

    while attempt < MAX_ATTEMPTS and not is_success:
        attempt += 1
        
        if session_id:
            # Thử sử dụng session cũ để lấy dữ liệu
            print(f"2.{attempt}. Đang thử lấy dữ liệu với Session cũ...")
            
            # Sử dụng hàm fetch_data đã sửa đổi
            accounts_response_data = fetch_data(GET_ACCOUNTS_API_BASE, session_id)
            
            if accounts_response_data:
                all_accounts_data = accounts_response_data
                print(f"✅ Lấy dữ liệu tài khoản tổng quan thành công bằng Session cũ! Tiếp tục.")
                is_success = True
                break # Thoát vòng lặp vì đã thành công
            else:
                # Lỗi API hoặc HTTP, cần đăng nhập lại
                login_required = True
                session_id = None # Đặt lại session_id cũ

        else:
            # Không có session ID cũ hoặc session cũ đã bị xóa/lỗi
            if attempt == 1:
                print("2.1. Không có Session ID cũ/hợp lệ. Tiến hành Đăng nhập...")
            login_required = True

        
        # Nếu cần đăng nhập, tiến hành đăng nhập
        if login_required:
            new_session = perform_login() # Hàm đăng nhập đã sửa lỗi
            if new_session:
                session_id = new_session
                save_session_to_db(db, session_id, timestamp_str) # Lưu session mới
                # Quay lại đầu vòng lặp để thử lại với session mới
                login_required = False
            else:
                # Đăng nhập thất bại, không thể tiếp tục
                print("❌ Đăng nhập thất bại và không thể lấy Session ID mới. Thoát.")
                break 

    # 4. Lưu dữ liệu Tài khoản Tổng quan vào Google Firebase Firestore
    print("-" * 40)
    if all_accounts_data and all_accounts_data.get('accounts'):
        num_accounts = len(all_accounts_data['accounts'])
        print(f"3. Đang Lưu dữ liệu tổng quan của {num_accounts} tài khoản vào Firestore...")

        # Tạo document snapshot (Theo cấu trúc laysession.py)
        snapshot_document = {
            'timestamp': timestamp_str,
            'source_api': 'myfxbook_get_my_accounts',
            'accounts_count': num_accounts,
            'data': all_accounts_data 
        }
        
        try:
            # Sử dụng timestamp làm tên ID Document
            doc_id = f'snapshot-{timestamp.strftime("%Y%m%d%H%M%S")}'
            doc_ref = db.collection(COLLECTION_NAME).document(doc_id)
            doc_ref.set(snapshot_document)
            print("✅ Dữ liệu tổng quan đã được lưu thành công vào Firestore với ID:", doc_id)
            
        except Exception as e:
            print(f"❌ Lỗi khi lưu vào Firestore: {e}")
    else:
        print("⚠️ Bỏ qua bước Lưu Dữ liệu Tổng quan: Không có dữ liệu tài khoản hợp lệ để lưu.")

    # 5. Lấy dữ liệu Lệnh đang mở (Tạo mảng tóm tắt)
    print("-" * 40)
    if all_accounts_data and all_accounts_data.get('accounts') and session_id:
        accounts_to_fetch = all_accounts_data['accounts']
        print(f"4. Bắt đầu lấy **số lượng lệnh đang mở** cho {len(accounts_to_fetch)} tài khoản...")
        
        for account in accounts_to_fetch:
            account_id = account.get('id')
            if account_id:
                # Gọi hàm và lưu kết quả tóm tắt vào danh sách
                summary_item = fetch_and_get_open_trades_summary(session_id, account_id)
                if summary_item:
                    open_trades_summary_list.append(summary_item) 
                
                # THÊM ĐỘ TRỄ NHỎ để tránh bị Rate Limit
                time.sleep(1) 
            else:
                print("    ⚠️ Bỏ qua một tài khoản: Không tìm thấy ID.")
                
        print("✅ Hoàn tất quá trình lấy số lệnh đang mở và tạo mảng tóm tắt.")

    else:
        print("⚠️ Bỏ qua bước Lấy Lệnh đang mở: Không có dữ liệu tài khoản hoặc Session ID.")

    # 6. LƯU MẢNG JSON TÓM TẮT LÊN FIRESTORE
    print("-" * 40)
    if open_trades_summary_list:
        print(f"5. Đang Lưu **Mảng Tóm Tắt** của {len(open_trades_summary_list)} tài khoản vào Firestore...")
        
        # Tạo document tóm tắt (Theo cấu trúc laysession.py)
        summary_document = {
            'timestamp': timestamp_str,
            'source_api': 'myfxbook_open_trades_summary',
            'accounts_count': len(open_trades_summary_list),
            'data': open_trades_summary_list # Đây là mảng JSON bạn muốn lưu
        }
        
        try:
            # Sử dụng timestamp làm tên ID Document để có thể theo dõi lịch sử
            doc_id = f'{SUMMARY_DOC_PREFIX}-{timestamp.strftime("%Y%m%d%H%M%S")}'
            doc_ref = db.collection(OPEN_TRADES_SUMMARY_COLLECTION).document(doc_id)
            doc_ref.set(summary_document)
            
            print("✅ Mảng JSON Tóm Tắt Lệnh Đang Mở Đã Tạo:")
            print(json.dumps(open_trades_summary_list, indent=4))
            print(f"✅ Đã lưu Mảng Tóm Tắt thành công vào Collection '{OPEN_TRADES_SUMMARY_COLLECTION}' với ID: {doc_id}")
            
        except Exception as e:
            print(f"❌ Lỗi khi lưu Mảng Tóm Tắt vào Firestore: {e}")
    else:
        print("⚠️ Bỏ qua bước Lưu Mảng Tóm Tắt: Danh sách rỗng.")

    print("-" * 40)
    print("🏁 Quy trình cho vòng chạy này hoàn tất.")


# --- THỰC THI CHÍNH (MAIN EXECUTION) ---
if __name__ == '__main__':
    
    print("\n" + "#" * 60)
    print("🚀 Bắt đầu Chế độ Chạy Một Lần theo Lịch trình (Tương thích GitHub Actions).")
    print("#" * 60)
    
    try:
        run_data_collection() 
    
    except Exception as e:
        # Xử lý các lỗi xảy ra ở cấp độ khởi tạo Firebase hoặc các lỗi nghiêm trọng khác
        print(f"\n‼️ FATAL ERROR: Lỗi không xác định xảy ra ở cấp độ ngoài cùng: {e}")
    
    print("\n" + "~" * 60)
    print("🏁 Tập lệnh đã hoàn thành và sẽ kết thúc.")
    print("~" * 60)
