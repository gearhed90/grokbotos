"""Minimal PAM password check through libpam (ctypes), for the Nova lock screen.
The secret is only held in memory for the PAM conversation and never logged."""
import ctypes, ctypes.util

PAM_SUCCESS = 0
PAM_PROMPT_ECHO_OFF = 1
PAM_PROMPT_ECHO_ON = 2


class PamMessage(ctypes.Structure):
    _fields_ = [("msg_style", ctypes.c_int), ("msg", ctypes.c_char_p)]


class PamResponse(ctypes.Structure):
    _fields_ = [("resp", ctypes.c_void_p), ("resp_retcode", ctypes.c_int)]


CONV_FUNC = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int,
                             ctypes.POINTER(ctypes.POINTER(PamMessage)),
                             ctypes.POINTER(ctypes.POINTER(PamResponse)), ctypes.c_void_p)


class PamConv(ctypes.Structure):
    _fields_ = [("conv", CONV_FUNC), ("appdata_ptr", ctypes.c_void_p)]


_libpam = None
_libc = None


def _libs():
    global _libpam, _libc
    if _libpam is None:
        _libpam = ctypes.CDLL(ctypes.util.find_library("pam") or "libpam.so.0")
        _libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
        _libc.calloc.restype = ctypes.c_void_p
        _libc.calloc.argtypes = (ctypes.c_size_t, ctypes.c_size_t)
        _libc.strdup.restype = ctypes.c_void_p
        _libc.strdup.argtypes = (ctypes.c_char_p,)
        _libpam.pam_start.argtypes = (ctypes.c_char_p, ctypes.c_char_p,
                                      ctypes.POINTER(PamConv), ctypes.POINTER(ctypes.c_void_p))
        _libpam.pam_authenticate.argtypes = (ctypes.c_void_p, ctypes.c_int)
        _libpam.pam_acct_mgmt.argtypes = (ctypes.c_void_p, ctypes.c_int)
        _libpam.pam_setcred.argtypes = (ctypes.c_void_p, ctypes.c_int)
        _libpam.pam_end.argtypes = (ctypes.c_void_p, ctypes.c_int)
    return _libpam, _libc


def authenticate(user, secret, service="grokbot-lock"):
    """True if PAM accepts secret for user. secret is str; it is encoded once and
    the copy handed to PAM is freed by PAM itself."""
    pam, libc = _libs()
    data = secret.encode()

    @CONV_FUNC
    def conv(n, msgs, resp, _app):
        arr = libc.calloc(n, ctypes.sizeof(PamResponse))
        if not arr:
            return 5  # PAM_BUF_ERR
        r = ctypes.cast(arr, ctypes.POINTER(PamResponse))
        for i in range(n):
            if msgs[i].contents.msg_style in (PAM_PROMPT_ECHO_OFF, PAM_PROMPT_ECHO_ON):
                r[i].resp = libc.strdup(data)
                r[i].resp_retcode = 0
        resp[0] = r
        return PAM_SUCCESS

    handle = ctypes.c_void_p()
    rc = pam.pam_start(service.encode(), user.encode(), ctypes.byref(PamConv(conv, None)),
                       ctypes.byref(handle))
    if rc != PAM_SUCCESS:
        return False
    try:
        rc = pam.pam_authenticate(handle, 0)
        if rc == PAM_SUCCESS:
            rc = pam.pam_acct_mgmt(handle, 0)
        if rc == PAM_SUCCESS:
            pam.pam_setcred(handle, 0x0008)  # PAM_REFRESH_CRED, like swaylock
        return rc == PAM_SUCCESS
    finally:
        pam.pam_end(handle, rc)
