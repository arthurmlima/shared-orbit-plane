#include <cstdint>
#include <algorithm>
extern "C" void evaluate(const uint8_t *a,const uint8_t *b,const uint8_t *c,const uint8_t *d,int n,int split,int *out) {
    int counts[41]={0};
    for(int i=0;i<split;i++) counts[0]+=((a[i]^b[i]^c[i])==d[i]);
    int k=1;
    for(int s1=-1;s1<=1;s1+=2) for(int s2=-1;s2<=1;s2+=2) for(int s3=-1;s3<=1;s3+=2){
        int hist[256]={0};
        for(int i=0;i<split;i++) hist[(d[i]-s1*a[i]-s2*b[i]-s3*c[i])&255]++;
        for(int off=-2;off<=2;off++)counts[k++]=hist[off&255];
    }
    int best=std::max_element(counts,counts+41)-counts,correct=0;
    if(best==0){for(int i=split;i<n;i++)correct+=((a[i]^b[i]^c[i])==d[i]);}
    else {
        int m=(best-1)/5, off=(best-1)%5-2;
        int s1=(m&4)?1:-1,s2=(m&2)?1:-1,s3=(m&1)?1:-1;
        for(int i=split;i<n;i++)correct+=(((s1*a[i]+s2*b[i]+s3*c[i]+off)&255)==d[i]);
    }
    out[0]=best;out[1]=counts[best];out[2]=correct;
}
