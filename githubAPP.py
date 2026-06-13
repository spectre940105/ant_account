import streamlit as st
import pandas as pd
from supabase import create_client, Client 

# ==========================================
# 1. 初始化 Supabase 原生 API 客戶端 (完全免除 TCP 鎖 Port 煩惱)
# ==========================================
def get_supabase_client() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

# ==========================================
# 2. 初始化 Session State (身分驗證狀態管理)
# ==========================================
if 'user_id' not in st.session_state:
    st.session_state['user_id'] = None
if 'username' not in st.session_state:
    st.session_state['username'] = None

# ==========================================
# 3. 側邊欄：會員登入與註冊系統 (API 化)
# ==========================================
st.sidebar.title("個人選單")

if st.session_state['user_id'] is None:
    auth_mode = st.sidebar.radio("切換功能", ["會員登入", "註冊新會員"])

    # 會員登入表單
    if auth_mode == "會員登入":
        auth_username = st.sidebar.text_input("帳號 (Username)", key="auth_user")
        auth_password = st.sidebar.text_input("密碼 (Password)", type="password", key="auth_pass")
        if st.sidebar.button("登入"):
            if auth_username and auth_password:
                supabase = get_supabase_client()
                try:
                    response = supabase.table("users") \
                        .select("user_id, username") \
                        .eq("username", auth_username) \
                        .eq("password_hash", auth_password) \
                        .execute()
                    
                    user_data = response.data
                    if user_data:
                        user = user_data[0]
                        st.session_state['user_id'] = user['user_id']
                        st.session_state['username'] = user['username']
                        st.sidebar.success(f"歡迎回來，{user['username']}！")
                        st.rerun()
                    else:
                        st.sidebar.error("帳號或密碼錯誤！")
                except Exception as e:
                    st.sidebar.error(f"連線異常：{e}")
            else:
                st.sidebar.warning("請輸入帳號與密碼")

    # 註冊新會員表單
    elif auth_mode == "註冊新會員":
        auth_username = st.sidebar.text_input("帳號 (Username)", max_chars=20, key="auth_user")
        auth_password = st.sidebar.text_input("密碼 (Password)", type="password", key="auth_pass")
        auth_email = st.sidebar.text_input("電子信箱 (Email)", key="auth_email")
        if st.sidebar.button("註冊"):
            if auth_username and auth_password:
                supabase = get_supabase_client()
                try:
                    supabase.table("users").insert({
                        "username": auth_username,
                        "password_hash": auth_password,
                        "email": auth_email
                    }).execute()
                    st.sidebar.success("註冊成功！請切換至登入畫面。")
                except Exception as e:
                    if "users_username_key" in str(e) or "duplicate" in str(e).lower():
                        st.sidebar.error("此帳號已被註冊！")
                    else:
                        st.sidebar.error(f"註冊失敗：{e}")
            else:
                st.sidebar.warning("帳號與密碼為必填項目")
else:
    st.sidebar.write(f"👤 當前登入：**{st.session_state['username']}**")
    if st.sidebar.button("登出系統"):
        st.session_state['user_id'] = None
        st.session_state['username'] = None
        st.rerun()


# ==========================================
# 4. 建立日常記帳局部刷新組件 (Fragment 1)
# ==========================================
@st.fragment
def render_transaction_form(current_user_id):
    st.subheader("📝 新增日常收支")
    supabase = get_supabase_client()

    try:
        # 🚀 轉換為 API 撈取該使用者帳戶 (含 Bank Name)
        acc_res = supabase.table("user_accounts").select("account_id, bank_id, account_name, balance").eq("user_id", current_user_id).execute()
        user_acc_df = pd.DataFrame(acc_res.data)

        # 🚀 轉換為 API 撈取所有銀行基本資料對齊別名
        bank_res = supabase.table("banks").select("bank_id, bank_name").execute()
        bank_df = pd.DataFrame(bank_res.data)
        
        if not user_acc_df.empty and not bank_df.empty:
            user_acc_df = user_acc_df.merge(bank_df, on="bank_id", how="left")

        # 🚀 轉換為 API 撈取分類
        cat_res = supabase.table("categories").select("category_id, category_name, category_type").execute()
        categories_df = pd.DataFrame(cat_res.data)
        categories_df['display'] = categories_df['category_name'] + " (" + categories_df['category_type'] + ")"

        if user_acc_df.empty:
            st.info("您目前尚未綁定任何銀行帳戶，請先在最下方完成綁定以開始記帳。")
        else:
            user_acc_df['display'] = user_acc_df.apply(lambda row: f"{row['bank_id']} {row['account_name']} (餘額: {int(float(row['balance']))})", axis=1)

            col_acc, col_type, col_cat = st.columns([3, 2, 3])
            with col_acc:
                chosen_acc = st.selectbox("帳戶選擇", options=user_acc_df.to_dict('records'), format_func=lambda x: x['display'])
            with col_type:
                chosen_type = st.radio("收支類型", options=["支出", "收入"], horizontal=True)
            with col_cat:
                filtered_cat_df = categories_df[categories_df['category_type'] == chosen_type]
                chosen_cat = st.selectbox("選擇交易分類", options=filtered_cat_df.to_dict('records'), format_func=lambda x: x['category_name'])

            tx_amount = st.number_input("交易金額", min_value=0.00, value=0.00, step=10.0)
            tx_desc = st.text_input("備註說明", placeholder="例如：購物、N月薪水")

            # 🚀 透過 RPC 直接呼叫你在 Supabase 雲端建好的預存程序 (Stored Procedure)
            if st.button("確認送出記帳"):
                try:
                    supabase.rpc("sp_inserttransaction", {
                        "p_account_id": int(chosen_acc['account_id']),
                        "p_category_id": int(chosen_cat['category_id']),
                        "p_amount": float(tx_amount),
                        "p_description": str(tx_desc)
                    }).execute()
                    st.success("記帳成功！資產餘額已自動計算更新。")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ 資料庫核心回報錯誤：{str(e)}")
    except Exception as e:
        st.error(f"組件載入異常：{e}")


# ==========================================
# 5. 建立開戶綁定銀行局部刷新組件
# ==========================================
@st.fragment
def render_bank_binding_form(current_user_id):
    st.subheader("綁定銀行帳戶")
    with st.expander("點擊展開 : 開戶功能"):
        supabase = get_supabase_client()
        try:
            bank_res = supabase.table("banks").select("bank_id, bank_name").execute()
            all_banks_df = pd.DataFrame(bank_res.data)
            all_banks_df['display'] = all_banks_df['bank_id'] + " - " + all_banks_df['bank_name']

            selected_bank = st.selectbox("選擇要綁定的銀行", options=all_banks_df.to_dict('records'), format_func=lambda x: x['display'])
            custom_acc_name = st.text_input("自訂帳戶別名 (例如：我的薪轉戶、生活費帳戶)", placeholder="可不填")
            init_balance = st.number_input("初始帳戶餘額", min_value=0.0, step=100.0)

            if st.button("確認綁定銀行"):
                chosen_bank_code = selected_bank['bank_id']
                final_alias = custom_acc_name.strip() if custom_acc_name.strip() else selected_bank['bank_name'].strip()

                check_res = supabase.table("user_accounts").select("bank_id").eq("user_id", current_user_id).execute()
                user_acc_df = pd.DataFrame(check_res.data)
                exsiting_banks = user_acc_df['bank_id'].astype(str).values if not user_acc_df.empty else []

                if str(chosen_bank_code) in exsiting_banks:
                    st.error("您已經綁定過此銀行了！請選擇其他銀行或刪除原有帳戶後再試。")
                else:
                    try:
                        supabase.table("user_accounts").insert({
                            "user_id": current_user_id,
                            "bank_id": chosen_bank_code,
                            "account_name": final_alias,
                            "balance": init_balance
                        }).execute()
                        st.success(f"🎉 成功綁定 {final_alias} 帳戶！")
                        st.rerun()
                    except Exception as e:
                        st.error(f"綁定失敗：{e}")
        except Exception as e:
            st.error(f"載入銀行列表失敗：{e}")


# ==========================================
# 6. 主畫面流程調度中心
# ==========================================
if st.session_state['user_id'] is not None:
    current_user_id = st.session_state['user_id']
    st.title(f"📊 {st.session_state['username']} 的個人財務管理系統")

    supabase = get_supabase_client()

    # 🚀 API 查詢總餘額
    balance_res = supabase.table("user_accounts").select("balance").eq("user_id", current_user_id).execute()
    user_balance_df = pd.DataFrame(balance_res.data)
    
    total_balance = user_balance_df['balance'].sum() if not user_balance_df.empty else 0.0

    col_metric, col_privacy = st.columns([3, 1])
    with col_privacy:
        st.write("")
        hide_balance = st.toggle("隱藏餘額", value=False, key="privacy_mode")

    with col_metric:
        if hide_balance:
            st.metric(label="💰總資產餘額 (隱藏)", value="****** 元")
        else:
            st.metric(label="💰總資產餘額", value=f"{total_balance:,.2f} 元")
    st.markdown("---")

    # 執行日常記帳局部組件
    render_transaction_form(current_user_id)
    st.markdown("---")

    # 🚀 API 查詢歷史明細 (直接讀取你在雲端建好的歷史明細檢視表 v_usertransactions)
    st.subheader("📜 歷史記帳明細與刪除")
    try:
        history_res = supabase.table("v_usertransactions").select("*").eq("user_id", current_user_id).order("tx_date", desc=True).execute()
        history_df = pd.DataFrame(history_res.data)
    except Exception:
        history_df = pd.DataFrame()

    if history_df.empty:
        st.write("目前尚無任何交易紀錄。")
    else:
        history_df['tx_date'] = pd.to_datetime(history_df['tx_date'])
        current_date = pd.Timestamp.now()
        current_year = current_date.year
        current_month = current_date.month

        if current_month == 1:
            prev_month = 12
            prev_year = current_year - 1
        else:
            prev_month = current_month - 1
            prev_year = current_year

        start_of_prev_month = pd.Timestamp(prev_year, prev_month, 1)
        filtered_df = history_df[history_df['tx_date'] >= start_of_prev_month]

        if filtered_df.empty:
            st.write(f"目前尚無 {prev_year} 年 {prev_month} ~ {current_month} 月的交易紀錄。")
        else:
            show_table = filtered_df.drop(columns=['tx_id', 'user_id'], errors='ignore')
            show_table = show_table.rename(columns={
                'bank_id': '銀行代碼', 'bank_name': '銀行名稱',
                'account_name': '帳戶別名', 'category_name': '分類',
                'transaction_type': '收支類型', 'amount': '金額',
                'tx_date': '交易時間', 'description': '備註'
            })
            show_table['交易時間'] = pd.to_datetime(show_table['交易時間']).dt.strftime('%Y-%m-%d')
            st.dataframe(show_table, use_container_width=True)

            st.subheader("⚠️ 記錯帳刪除區")
            tx_to_delete = st.selectbox(
                "選擇欲刪除的交易序號",
                options=history_df.to_dict('records'),
                format_func=lambda x: f"時間: {x['tx_date'].strftime('%Y-%m-%d')} | 帳戶: {x['account_name']} | 分類: {x['category_name']} | 金額: {int(float(x['amount']))} | 類型: {x['transaction_type']}"
            )

            if st.button("確認刪除此筆交易"):
                try:
                    # 🚀 API 刪除紀錄，觸發雲端 Trigger 自動回滾金額
                    supabase.table("transactions").delete().eq("tx_id", tx_to_delete['tx_id']).execute()
                    st.success(f"交易序號 {tx_to_delete['tx_id']} 已刪除！資料庫 Trigger 已跨時空將金額完美校正。")
                    st.rerun()
                except Exception as e:
                    st.error(f"刪除失敗：{e}")

    st.markdown("---")
    # 執行開戶綁定局部組件
    render_bank_binding_form(current_user_id)
    st.markdown("---")

else:
    st.title("💰 歡迎使用螞蟻記帳系統")
    st.info("👈 請先透過左側邊欄進行【會員登入】或【註冊新會員】以開始使用系統。")
