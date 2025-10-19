import requests
import json
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
# import time # ❌ Đã xóa thư viện time vì không cần time.sleep()

# --- Cấu hình API Myfxbook ---
# ⚠️ THAY THẾ BẰNG THÔNG TIN THỰC TẾ CỦA BẠN
MY_EMAIL = "hai12b3@gmail.com"  
MY_PASSWORD = "Hadeshai5"        
LOGIN_API = f"https://www.myfxbook.com/api/login.json?email={MY_EMAIL}&password={MY_PASSWORD}"
GET_ACCOUNTS_API_BASE = "https://www.myfxbook.com/api/get-my-accounts.json"
GET_OPEN_TRADES_API_BASE = "https://www.myfxbook.com/api/get-open-trades.json"

# --- Cấu hình Firebase ---
# Tên tệp khóa Service Account: Đây là tệp sẽ được tạo bởi GitHub Actions Secret
SERVICE_ACCOUNT_FILE = 'datafx-45432-firebase-adminsdk-fbsvc-3132a63c50.json' 
COLLECTION_NAME = 'myfxbook_snapshots'      
OPEN_TRADES_SUMMARY_COLLECTION = 'myfxbook_trades_summary' 
SESSION_DOC_ID = 'current_session'          
TRADES_DOC_ID = 'current_trades_summary'     

# ❌ Đã loại bỏ firebase_app toàn cục và khởi tạo
# Khởi tạo Firebase sẽ được thực hiện trong hàm run_data_collection

def initialize_firebase():
    """Khởi tạo Firebase Admin SDK."""
    try:
        # Kiểm tra xem ứng dụng Firebase đã được khởi tạo chưa
        if not firebase_admin._apps:
            cred = credentials.Certificate(SERVICE_ACCOUNT_FILE)
            firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        print(f"❌ Lỗi khi khởi tạo Firebase: {e}")
        # Đây là lỗi nghiêm trọng, ta nên dừng lại
        raise

def get_session_id():
    """Lấy Session ID bằng cách đăng nhập."""
    print("⏳ Đang đăng nhập để lấy Session ID...")
    try:
        response = requests.get(LOGIN_API)
        response.raise_for_status() # Báo lỗi cho các mã trạng thái HTTP xấu
        data = response.json()
        
        if data.get('success') and data.get('session'):
            session_id = data['session']
            print(f"✅ Đăng nhập thành công! Session ID: {session_id[:10]}...")
            return session_id
        else:
            print(f"❌ Đăng nhập thất bại: {data.get('message')}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Lỗi kết nối API Myfxbook: {e}")
        return None

def fetch_data(api_url, session_id):
    """Lấy dữ liệu từ API Myfxbook."""
    full_url = f"{api_url}?session={session_id}"
    try:
        response = requests.get(full_url)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.exceptions.RequestException as e:
        print(f"❌ Lỗi khi lấy dữ liệu từ {api_url}: {e}")
        return None

def save_snapshot_to_firestore(db, data):
    """Lưu dữ liệu snapshot vào Firestore."""
    try:
        # Lấy timestamp hiện tại
        current_time = datetime.now()
        timestamp_str = current_time.isoformat()
        
        # Tạo document dữ liệu
        document_data = {
            'timestamp': timestamp_str,
            'data': data.get('accounts', []),
            'success': data.get('success', False)
        }
        
        # 1. Lưu vào document với ID cố định (để hiển thị dashboard)
        doc_ref = db.collection(COLLECTION_NAME).document(SESSION_DOC_ID)
        doc_ref.set(document_data)
        
        # 2. Lưu một bản sao có ID là timestamp (để lưu trữ lịch sử)
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
        
        # Bước 1: Tổng hợp số lượng lệnh đang mở theo accountId
        for acc in open_trades_data['accounts']:
            account_id_long = acc.get('id') 
            trades = acc.get('trades', [])
            
            if account_id_long:
                # Lấy ID số ngắn (ví dụ: "11562646") từ chuỗi ID dài
                # Ví dụ: "11562646-202510xxxx" -> "11562646"
                short_id_match = str(account_id_long).split('-')[0]
                
                accounts_with_trades[short_id_match] = {
                    'account_id': account_id_long,
                    'open_trades_count': len(trades)
                }

        # Bước 2: Chuyển đổi thành mảng JSON để lưu
        open_trades_summary_list = list(accounts_with_trades.values())
        
        if open_trades_summary_list:
            
            # Tạo document để lưu vào Firestore
            current_time = datetime.now()
            doc_id = TRADES_DOC_ID
            
            summary_document = {
                'timestamp': current_time.isoformat(),
                'data': open_trades_summary_list,
                'success': True
            }
            
            # Lưu vào document với ID cố định
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
        # 1. Khởi tạo Firebase và lấy đối tượng DB
        db = initialize_firebase()
        
        # 2. Đăng nhập để lấy Session ID
        session_id = get_session_id()
        if not session_id:
            print("❌ Không có Session ID, dừng quy trình.")
            return

        # 3. Lấy dữ liệu Snapshot tài khoản
        print("⏳ Đang lấy dữ liệu Snapshot Tài khoản...")
        account_snapshot_data = fetch_data(GET_ACCOUNTS_API_BASE, session_id)
        
        if account_snapshot_data and account_snapshot_data.get('success'):
            print(f"✅ Đã tải về {len(account_snapshot_data.get('accounts', []))} tài khoản.")
            save_snapshot_to_firestore(db, account_snapshot_data)
        else:
            print(f"❌ Lỗi khi lấy dữ liệu Snapshot: {account_snapshot_data.get('message', 'Không rõ lỗi')}")

        # 4. Lấy dữ liệu Lệnh Đang Mở (Open Trades)
        print("⏳ Đang lấy dữ liệu Lệnh Đang Mở...")
        open_trades_data = fetch_data(GET_OPEN_TRADES_API_BASE, session_id)
        
        if open_trades_data and open_trades_data.get('success'):
            save_open_trades_summary(db, open_trades_data)
        else:
             print(f"❌ Lỗi khi lấy dữ liệu Lệnh Đang Mở: {open_trades_data.get('message', 'Không rõ lỗi')}")

    except Exception as e:
        print(f"‼️ Lỗi nghiêm trọng trong quá trình chạy: {e}")

    print("-" * 40)
    print("🏁 Quy trình cho vòng chạy này hoàn tất.")


# --- THỰC THI (MAIN EXECUTION) ---
if __name__ == '__main__':
    
    print("\n" + "#" * 60)
    print("🚀 Bắt đầu Chế độ Chạy Một Lần theo Lịch trình (GitHub Actions).")
    print("#" * 60)
    
    try:
        # Gọi hàm chứa toàn bộ quy trình thu thập dữ liệu
        run_data_collection() 
    
    except Exception as e:
        # Xử lý các lỗi không lường trước
        print(f"\n‼️ FATAL ERROR: Lỗi không xác định xảy ra: {e}")
    
    print("\n" + "~" * 60)
    print("🏁 Tập lệnh đã hoàn thành và sẽ kết thúc.")
    print("~" * 60)
    
    # ❌ Đã loại bỏ time.sleep() và vòng lặp while True
