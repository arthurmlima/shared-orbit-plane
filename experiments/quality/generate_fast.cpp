#include <cstdint>
static uint64_t xs(uint64_t x){x^=x<<13;x^=x>>7;x^=x<<17;return x;}
static uint32_t tent(uint32_t x){return ((x^((x>>31)?0xffffffffu:0u))<<1)|(((x>>1)^x)&1u);}
extern "C" void generate(const uint64_t *seed,uint8_t *out,int tiles,int n,int mode){
 for(int tile=0;tile<tiles;tile++){
  uint64_t x=seed[tile];
  for(int t=0;t<n;t++){
   uint8_t b=0;
   if(mode==0||mode==2)b=uint8_t(x);
   else if(mode==3)b=uint8_t(x>>8);
   else if(mode==1)for(int k=56;k>=0;k-=8)b=uint8_t((b<<1)|((x>>k)&1));
   else if(mode==4)for(int k=30;k>=2;k-=4)b=uint8_t((b<<1)|((x>>k)&1));
   out[tile*n+t]=b;
   x=(mode<=1)?xs(x):tent(uint32_t(x));
  }
 }
}
extern "C" void generate_logistic(const uint64_t *seed,const uint64_t *pert_seed,uint8_t *out,int tiles,int n){
 for(int tile=0;tile<tiles;tile++){
  uint32_t x=uint32_t(seed[tile]);uint64_t p=pert_seed[tile];
  for(int t=-65;t<n;t++){
   if(t>=0)out[tile*n+t]=uint8_t(x>>8);
   uint64_t rx=(uint64_t(x)<<2)-(uint64_t(x)>>6);
   uint64_t mapped=uint64_t(((__uint128_t)rx*((1ull<<32)-x))>>32);
   p=xs(p);x=uint32_t(mapped^(p&255));
  }
 }
}
