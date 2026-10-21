/* Sobel edge/contour detection split into 8 IP/CV steps:
 *  0 input | 1 mean3x3(0) | 2 sobelX(1) | 3 sobelY(1) | 4 abs(2) | 5 abs(3)
 *  6 = 4 + 5 | 7 global threshold(6)
 * Every Tile runs the same program on its own region. */
#include "mpriscv.h"

static const int K_MEAN[9] = { 1, 1, 1,  1, 1, 1,  1, 1, 1 };
static const int K_SX[9]   = {-1, 0, 1, -2, 0, 2, -1, 0, 1 };
static const int K_SY[9]   = {-1,-2,-1,  0, 0, 0,  1, 2, 1 };

static int clampi(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

static void conv3x3(const int *k, int div, int src, int dst,
                    int x0, int y0, int tw, int th, int w, int h)
{
    for (int y = y0; y < y0 + th; y++)
        for (int x = x0; x < x0 + tw; x++) {
            int acc = 0;
            for (int j = -1; j <= 1; j++)
                for (int i = -1; i <= 1; i++) {
                    int xx = clampi(x + i, 0, w - 1);
                    int yy = clampi(y + j, 0, h - 1);
#ifdef SKIP_ZERO_TAPS
                    if (k[(j + 1) * 3 + (i + 1)] == 0) continue;   /* Sobel: 6 of 9 taps */
#endif
                    acc += k[(j + 1) * 3 + (i + 1)] * get_pixel(xx, yy, src, 0);
                }
            set_pixel(acc / div, x, y, dst, 0);
        }
}

static void absolute(int src, int dst, int x0, int y0, int tw, int th)
{
    for (int y = y0; y < y0 + th; y++)
        for (int x = x0; x < x0 + tw; x++) {
            int v = get_pixel(x, y, src, 0);
            set_pixel(v < 0 ? -v : v, x, y, dst, 0);
        }
}

static void add(int a, int b, int dst, int x0, int y0, int tw, int th)
{
    for (int y = y0; y < y0 + th; y++)
        for (int x = x0; x < x0 + tw; x++)
            set_pixel(get_pixel(x, y, a, 0) + get_pixel(x, y, b, 0), x, y, dst, 0);
}


/* Global threshold = mean of the whole image's step-`src` values, independent of how the
 * image is partitioned. Each Tile publishes its 32-bit local sum as two 16-bit pixels of
 * step `dst` at its own origin, then gathers the N*N partial sums (Tile origins follow the
 * same balanced partition rule as the hardware: x0(i) = i*W/N). */
static int global_mean(int local_sum, int dst, int x0, int y0, int w, int h, int n)
{
    set_pixel(local_sum & 0xffff, x0, y0, dst, 0);
    set_pixel((local_sum >> 16) & 0xffff, x0 + 1, y0, dst, 0);
    barrier();
    unsigned total = 0;
    for (int ty = 0; ty < n; ty++)
        for (int tx = 0; tx < n; tx++) {
            int ox = MP_ORG(tx, w, n), oy = MP_ORG(ty, h, n);
            unsigned lo = get_pixel(ox, oy, dst, 0) & 0xffff;
            unsigned hi = get_pixel(ox + 1, oy, dst, 0) & 0xffff;
            total += (hi << 16) | lo;
        }
    barrier();
    return (int)(total / (unsigned)(w * h));
}

static void global_threshold(int src, int dst, int x0, int y0, int tw, int th, int w, int h, int n)
{
    int sum = 0;
    for (int y = y0; y < y0 + th; y++)
        for (int x = x0; x < x0 + tw; x++)
            sum += get_pixel(x, y, src, 0);
    int t = global_mean(sum, dst, x0, y0, w, h, n);
    for (int y = y0; y < y0 + th; y++)
        for (int x = x0; x < x0 + tw; x++)
            set_pixel(get_pixel(x, y, src, 0) > t ? 255 : 0, x, y, dst, 0);
}

int main(void)
{
    int x0 = mp_xinit(), y0 = mp_yinit(), tw = mp_tw(), th = mp_th();
    int w = mp_img_w(), h = mp_img_h(), n = mp_n();

    mark(1); conv3x3(K_MEAN, 9, 0, 1, x0, y0, tw, th, w, h); barrier();
    mark(2); conv3x3(K_SX,   1, 1, 2, x0, y0, tw, th, w, h); barrier();
    mark(3); conv3x3(K_SY,   1, 1, 3, x0, y0, tw, th, w, h); barrier();
    mark(4); absolute(2, 4, x0, y0, tw, th);                 barrier();
    mark(5); absolute(3, 5, x0, y0, tw, th);                 barrier();
    mark(6); add(4, 5, 6, x0, y0, tw, th);                   barrier();
    mark(7); global_threshold(6, 7, x0, y0, tw, th, w, h, n);      barrier();
    mark(8);
    return 0;
}
