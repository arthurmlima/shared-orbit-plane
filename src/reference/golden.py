"""Bit-exact Python reference of the 8-step Sobel application (same integer ops as Tile-code)."""
import numpy as np

def cdiv(a, b):  # C integer division (truncate toward zero)
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b > 0) else -q

K_MEAN = [1]*9
K_SX = [-1,0,1,-2,0,2,-1,0,1]
K_SY = [-1,-2,-1,0,0,0,1,2,1]

def conv(src, k, div):
    H, W = src.shape
    out = np.zeros_like(src)
    for y in range(H):
        for x in range(W):
            acc = 0
            for j in (-1,0,1):
                for i in (-1,0,1):
                    xx = min(max(x+i,0),W-1); yy = min(max(y+j,0),H-1)
                    acc += k[(j+1)*3+(i+1)] * int(src[yy,xx])
            out[y,x] = cdiv(acc, div)
    return out

def pipeline(img, n):
    H, W = img.shape
    s = [None]*8
    s[0] = img.astype(np.int64)
    s[1] = conv(s[0], K_MEAN, 9)
    s[2] = conv(s[1], K_SX, 1)
    s[3] = conv(s[1], K_SY, 1)
    s[4] = np.abs(s[2]); s[5] = np.abs(s[3]); s[6] = s[4] + s[5]
    # global mean of step 6 (partition independent; n kept for API compatibility)
    t = int(s[6].sum()) // (W * H)
    s[7] = np.where(s[6] > t, 255, 0)
    return s, t
