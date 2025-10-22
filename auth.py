import toml
import os
import hashlib
import bcrypt
from typing import Optional, Dict, Any
import streamlit as st


class AuthManager:
    """认证管理器，处理密钥的设置、验证和存储"""

    def __init__(self, config_file: str = "auth_config.toml"):
        self.config_file = config_file
        self._ensure_config_exists()

    def _ensure_config_exists(self):
        """确保配置文件存在"""
        if not os.path.exists(self.config_file):
            # 创建默认配置文件
            default_config = {
                "auth": {
                    "access_key_hash": None,
                    "salt": None,
                    "is_configured": False
                }
            }
            with open(self.config_file, 'w', encoding='utf-8') as f:
                toml.dump(default_config, f)

    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                config = toml.load(f)
                return config.get("auth", {})
        except (FileNotFoundError, toml.TomlDecodeError):
            return {"access_key_hash": None, "salt": None, "is_configured": False}

    def _save_config(self, config: Dict[str, Any]):
        """保存配置文件"""
        full_config = {"auth": config}
        with open(self.config_file, 'w', encoding='utf-8') as f:
            toml.dump(full_config, f)

    def set_access_key(self, access_key: str) -> bool:
        """设置访问密钥"""
        try:
            # 生成盐值
            salt = bcrypt.gensalt()
            # 生成密码哈希
            key_hash = bcrypt.hashpw(access_key.encode('utf-8'), salt)

            # 保存配置
            config = {
                "access_key_hash": key_hash.decode('utf-8'),
                "salt": salt.decode('utf-8'),
                "is_configured": True
            }
            self._save_config(config)
            return True
        except Exception as e:
            st.error(f"设置密钥失败: {e}")
            return False

    def verify_access_key(self, access_key: str) -> bool:
        """验证访问密钥"""
        try:
            config = self._load_config()

            if not config.get("is_configured"):
                return False

            stored_hash = config.get("access_key_hash")
            if not stored_hash:
                return False

            # 验证密码
            return bcrypt.checkpw(access_key.encode('utf-8'), stored_hash.encode('utf-8'))
        except Exception as e:
            st.error(f"验证密钥失败: {e}")
            return False

    def is_configured(self) -> bool:
        """检查是否已配置密钥"""
        config = self._load_config()
        return config.get("is_configured", False)

    
    

def render_auth_setup(auth_manager: AuthManager) -> bool:
    """渲染密钥设置界面"""
    st.title("🔐 设置访问密钥")
    st.markdown("---")

    st.info("请设置一个访问密钥来保护您的专利撰写助手。此密钥将用于验证用户访问权限。")

    with st.form("setup_auth_form"):
        access_key = st.text_input(
            "访问密钥",
            type="password",
            help="请输入一个强密码作为访问密钥"
        )
        confirm_key = st.text_input(
            "确认密钥",
            type="password"
        )

        submitted = st.form_submit_button("🔒 设置密钥", type="primary")

        if submitted:
            if not access_key:
                st.error("请输入访问密钥")
            elif len(access_key) < 6:
                st.error("密钥长度至少需要6个字符")
            elif access_key != confirm_key:
                st.error("两次输入的密钥不一致")
            else:
                if auth_manager.set_access_key(access_key):
                    st.session_state.authenticated = True
                    st.success("✅ 密钥设置成功！正在进入应用...")
                    st.rerun()
                else:
                    st.error("❌ 密钥设置失败，请重试")

    return False


def render_login_screen(auth_manager: AuthManager) -> bool:
    """渲染登录界面"""
    st.title("🔐 专利撰写助手 - 身份验证")
    st.markdown("---")

    # 检查是否是首次使用（未设置密钥）
    if not auth_manager.is_configured():
        st.info("ℹ️ 系统尚未配置访问密钥，将自动跳转到设置页面")
        st.session_state.auth_stage = "setup"
        st.rerun()
        return False

    with st.form("login_form"):
        st.markdown("### 请输入访问密钥以继续")
        access_key = st.text_input("访问密钥", type="password")

        submitted = st.form_submit_button("🚀 登录", type="primary")

        if submitted:
            if not access_key:
                st.error("请输入访问密钥")
            elif auth_manager.verify_access_key(access_key):
                st.session_state.authenticated = True
                st.success("✅ 验证成功！正在进入...")
                st.rerun()
            else:
                st.error("❌ 密码错误，请重试")

    return False


def check_authentication(auth_manager: AuthManager) -> bool:
    """检查用户认证状态"""
    # 检查是否已认证
    if st.session_state.get("authenticated", False):
        return True

    # 检查认证阶段
    auth_stage = st.session_state.get("auth_stage", "login")

    if auth_stage == "setup":
        return render_auth_setup(auth_manager)
    else:
        return render_login_screen(auth_manager)