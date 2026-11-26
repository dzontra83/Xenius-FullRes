#include <stdio.h>
#include <stdlib.h>
#include <time.h>
int tbin_run(const unsigned short*, int, int, int, unsigned short*, int, int);
int main(int c, char** v){
  FILE* f=fopen(v[1],"rb"); fseek(f,103784,SEEK_SET);
  int W=16320,H=12256; unsigned short* s=malloc((size_t)W*H*2); fread(s,2,(size_t)W*H,f); fclose(f);
  unsigned short* d=malloc(8192*6144*2);
  struct timespec a,b; clock_gettime(CLOCK_MONOTONIC,&a);
  int r=tbin_run(s,W*2,W,H,d,64,1023);
  clock_gettime(CLOCK_MONOTONIC,&b);
  printf("rc %d %.3f s\n",r,(b.tv_sec-a.tv_sec)+(b.tv_nsec-a.tv_nsec)/1e9);
  FILE* o=fopen(v[2],"wb"); fwrite(d,2,8192*6144,o); fclose(o);
}
