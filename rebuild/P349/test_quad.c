#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <pthread.h>
int quad_start(const unsigned short*, int, int, int, unsigned short*);
void tbin_work(void); int tbin_finish(void);
static void* wk(void* a){ tbin_work(); return 0; }
int main(int c, char** v){
  int W=c>5?atoi(v[5]):8160,H=c>6?atoi(v[6]):6128,OW=8192,OH=6144;   /* tq in out threads mode [W H] */
  unsigned short* s=calloc((size_t)OW*OH,2); FILE* f=fopen(v[1],"rb");
  for(int y=0;y<H;y++) if(fread(s+(size_t)y*OW,2,W,f)!=(size_t)W) return 1;
  fclose(f);
  unsigned short* d=malloc((size_t)OW*OH*2); int nt=atoi(v[3]);
  struct timespec a,b; clock_gettime(CLOCK_MONOTONIC,&a);
  int r=quad_start(s,OW*2,W|((c>4?atoi(v[4]):0)<<16),H,d);
  pthread_t th[16]; for(int i=0;i<nt-1;i++) pthread_create(&th[i],0,wk,0);
  tbin_work(); for(int i=0;i<nt-1;i++) pthread_join(th[i],0);
  r|=tbin_finish();
  clock_gettime(CLOCK_MONOTONIC,&b);
  printf("rc %d threads %d %.3f s\n",r,nt,(b.tv_sec-a.tv_sec)+(b.tv_nsec-a.tv_nsec)/1e9);
  FILE* o=fopen(v[2],"wb"); fwrite(d,2,(size_t)OW*OH,o); fclose(o);
}
