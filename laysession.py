import requests
import json
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
from firebase_admin import exceptions as firebase_exceptions # 🆕 Thêm để bắt lỗi Firebase cụ thể

# --- Cấu hình API Myfxbook ---
# ⚠️ THAY THẾ BẰNG THÔNG TIN THỰC TẾ CỦA BẠN
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
TRADES_DOC_ID = 'current_trades_summary'     

def initialize_firebase():
    """Khởi tạo Firebase Admin SDK."""
    try:
        # Kiểm tra xem ứng dụng Firebase đã được khởi tạo chưa
        if not firebase_admin._apps:
            cred = credentials.Certificate(SERVICE_ACCOUNT_FILE)
            firebase_admin.initialize_app(cred)
        return firestore.client()
    except firebase_exceptions.FirebaseError as fe:
        print(f"❌ LỖI FIREBASE CỤ THỂ: Không thể khởi tạo. Vui lòng kiểm tra file khóa {SERVICE_ACCOUNT_FILE} và Secret: {fe}")
        raise
    except Exception as e:
        print(f"❌ LỖI KHỞI TẠO CHUNG: {e}")
        raise

def get_session_id():
    """Lấy Session ID bằng cách đăng nhập."""
    print("⏳ Đang đăng nhập để lấy Session ID...")
    try:
        response = requests.get(LOGIN_API, timeout=30) # 🆕 Thêm timeout
        
        # 🆕 Bắt lỗi HTTP trước khi cố gắng parse JSON
        if response.status_code != 200:
            print(f"❌ Lỗi HTTP: Status Code {response.status_code}. Phản hồi của server: {response.text}")
            response.raise_for_status() # Gây ra ngoại lệ HTTP
        
        data = response.json()
        
        if data.get('success') and data.get('session'):
            session_id = data['session']
            print(f"✅ Đăng nhập thành công! Session ID: {session_id[:10]}...")
            return session_id
        else:
            # 🆕 In ra toàn bộ thông báo lỗi JSON từ Myfxbook
            print("❌ Đăng nhập thất bại. Mã phản hồi JSON (Kiểm tra Email/Password):")
            print(json.dumps(data, indent=4))
            return None
            
    except requests.exceptions.Timeout:
        print("❌ LỖI MẠNG: Đăng nhập bị Timeout (Quá 30 giây).")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ LỖI KẾT NỐI API Myfxbook (Đăng nhập): {e}")
        return None
    except json.JSONDecodeError:
        print(f"❌ LỖI PHÂN TÍCH JSON: Phản hồi không phải JSON hợp lệ. Nội dung: {response.text[:100]}...")
        return None


def fetch_data(api_url, session_id):
    """Lấy dữ liệu từ API Myfxbook."""
    full_url = f"{api_url}?session={session_id}"
    try:
        response = requests.get(full_url, timeout=30)
        
        if response.status_code != 200:
            print(f"❌ Lỗi HTTP: Status Code {response.status_code} khi gọi {api_url}")
            response.raise_for_status()
            
        data = response.json()
        
        if not data.get('success'):
            print(f"❌ API báo lỗi khi gọi {api_url}. JSON phản hồi:")
            print(json.dumps(data, indent=4))
            return None # Trả về None nếu Myfxbook báo lỗi
            
        return data # Trả về dữ liệu nếu success = true
        
    except requests.exceptions.Timeout:
        print(f"❌ LỖI MẠNG: Gọi API {api_url} bị Timeout.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ LỖI KẾT NỐI API Myfxbook ({api_url}): {e}")
        return None
    except json.JSONDecodeError:
        print(f"❌ LỖI PHÂN TÍCH JSON: Phản hồi không phải JSON hợp lệ từ {api_url}. Nội dung: {response.text[:100]}...")
        return None

# ... (Các hàm save_snapshot_to_firestore và save_open_trades_summary giữ nguyên) ...
# Lưu ý: Các hàm lưu dữ liệu không thay đổi vì chúng không phải là nguyên nhân gây lỗi API.

def save_snapshot_to_firestore(db, data):
    """Lưu dữ liệu snapshot vào Firestore."""
    try:
        current_time = datetime.now()
        timestamp_str = current_time.isoformat()
        document_data = {
            'timestamp': timestamp_str,
            'data': data.get('accounts', []),
            'success': data.get('success', False)
        }
        doc_ref = db.collection(COLLECTION_NAME).document(SESSION_DOC_ID)
        doc_ref.set(document_data)
        history_doc_id = current_time.strftime("%Y%m%d_%H%M%S")
        history_doc_ref = db.collection(COLLECTION_NAME).document(history_doc_id)
        history_doc_ref.set(document_data)
        print(f"✅ Đã lưu Snapshot thành công. ID Dashboard: {SESSION_DOC_ID}, ID History: {history_doc_id}")
    except Exception as e:
        print(f"❌ Lỗi khi lưu Snapshot vào Firestore: {e}")

def save_open_trades_summary(db, open_trades_data):
    """Tạo và lưu mảng tóm tắt số lệnh đang mở vào collection riêng."""
    accounts_with_trades = {}
    
    if open_trades_data and open_trades_data.get('accounts'):
        for acc in open_trades_data['accounts']:
            account_id_long = acc.get('id') 
            trades = acc.get('trades', [])
            if account_id_long:
                short_id_match = str(account_id_long).split('-')[0]
                accounts_with_trades[short_id_match] = {
                    'account_id': account_id_long,
                    'open_trades_count': len(trades)
                }

        open_trades_summary_list = list(accounts_with_trades.values())
        
        if open_trades_summary_list:
            try:
                current_time = datetime.now()
                doc_id = TRADES_DOC_ID
                summary_document = {
                    'timestamp': current_time.isoformat(),
                    'data': open_trades_summary_list,
                    'success': True
                }
                doc_ref = db.collection(OPEN_TRADES_SUMMARY_COLLECTION).document(doc_id)
                doc_ref.set(summary_document)
                print("✅ Mảng JSON Tóm Tắt Lệnh Đang Mở Đã Tạo:")
                print(json.dumps(open_trades_summary_list, indent=4))
                print(f"✅ Đã lưu Mảng Tóm Tắt thành công vào Collection '{OPEN_TRADES_SUMMARY_COLLECTION}' với ID: {doc_id}")
                
            except Exception as e:
                print(f"❌ Lỗi khi lưu Mảng Tóm Tắt vào Firestore: {e}")
    else:
        print("⚠️ Bỏ qua bước Lưu Mảng Tóm Tắt: Danh sách rỗng.")

def run_data_collection():
    """Thực hiện toàn bộ quy trình thu thập và lưu dữ liệu."""
    try:
        # 1. Khởi tạo Firebase
        db = initialize_firebase()
        
        # 2. Đăng nhập để lấy Session ID
        session_id = get_session_id()
        if not session_id:
            print("❌ Không có Session ID, dừng quy trình.")
            return

        # 3. Lấy dữ liệu Snapshot tài khoản
        print("⏳ Đang lấy dữ liệu Snapshot Tài khoản...")
        account_snapshot_data = fetch_data(GET_ACCOUNTS_API_BASE, session_id)
        
        if account_snapshot_data: # Chỉ kiểm tra nếu dữ liệu không phải là None
            print(f"✅ Đã tải về {len(account_snapshot_data.get('accounts', []))} tài khoản.")
            save_snapshot_to_firestore(db, account_snapshot_data)
        else:
            # Thông báo lỗi đã được in ra trong hàm fetch_data
            pass 

        # 4. Lấy dữ liệu Lệnh Đang Mở (Open Trades)
        print("⏳ Đang lấy dữ liệu Lệnh Đang Mở...")
        open_trades_data = fetch_data(GET_OPEN_TRADES_API_BASE, session_id)
        
        if open_trades_data:
            save_open_trades_summary(db, open_trades_data)
        else:
            # Thông báo lỗi đã được in ra trong hàm fetch_data
            pass

    except Exception as e:
        print(f"‼️ LỖI NGHIÊM TRỌNG TRONG QUÁ TRÌNH CHẠY: {e}. Vui lòng kiểm tra lại cấu hình.")

    print("-" * 40)
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
