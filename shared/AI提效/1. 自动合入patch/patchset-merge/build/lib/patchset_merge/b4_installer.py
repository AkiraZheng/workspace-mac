"""b4 工具安装和版本检查"""
import subprocess
import sys

def check_b4_installed() -> bool:
    """检查 b4 是否已安装"""
    try:
        result = subprocess.run(['b4', '--version'], capture_output=True, text=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False

def install_b4() -> bool:
    """通过 pip 安装 b4"""
    result = subprocess.run([sys.executable, '-m', 'pip', 'install', 'b4'], capture_output=True, text=True)
    return result.returncode == 0

def ensure_b4() -> bool:
    """确保 b4 已安装，如未安装则自动安装"""
    if check_b4_installed():
        print("b4 is already installed")
        return True
    print("b4 not found, installing...")
    return install_b4()
