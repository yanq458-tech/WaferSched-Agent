// Integer difference-bound reachability for one frozen routing and repair tick.
// stdin: n,m,P,L,d,q,failed; then routed jobs: chamber,processing,ready,due,residence,hold,initialTravel.
using System;
using System.IO;
using System.Linq;
using System.Diagnostics;
using System.Collections.Generic;
class ZoneSearch {
 const int INF=10000000, M=5, T=1;
 static int n,m,S,P,L,d,q,F; static int[] chamber,proc,ready,due,res,hold,first,bit,steps,answer;
 static int[][] latest; static int[] initMasks,occ;static int[][] layers;static int[] remaining;
 static long nodes,hits;static Stopwatch watch;static double seconds;
 static bool reverse;static int[] releaseV,latestV,loadDue;static bool timeout;static int entries; static Dictionary<ulong,List<int[]>> memo=new Dictionary<ulong,List<int[]>>();
 static bool Tight(int[] z,int x,int y,int k) {
  if(z[x*M+y]<=k)return true;
  if(z[y*M+x]+k<0)return false;
  for(int a=0;a<M;a++){int ax=z[a*M+x];if(ax==INF)continue;int t=ax+k;
   for(int b=0;b<M;b++){int yb=z[y*M+b];if(yb!=INF && t+yb<z[a*M+b])z[a*M+b]=t+yb;}
  }return true;
 }
 static void Wait(int[] z){for(int j=0;j<M;j++)if(j!=T)z[T*M+j]=INF;}
 static void Shift(int[] z){for(int j=0;j<M;j++)if(j!=T){if(z[T*M+j]!=INF)z[T*M+j]+=S;if(z[j*M+T]!=INF)z[j*M+T]-=S;}}
 static void Forget(int[] z,int c){for(int j=0;j<M;j++)if(j!=c)z[c*M+j]=z[j*M+c]=INF;z[c*M+c]=0;}
 static void CopyClock(int[] z,int c){for(int j=0;j<M;j++)if(j!=c){z[c*M+j]=z[T*M+j];z[j*M+c]=z[j*M+T];}z[c*M+c]=0;}
 static bool Covered(int[] z,ulong key){
  List<int[]> states;
  if(memo.TryGetValue(key,out states)){
   for(int i=states.Count-1;i>=0;i--){int[] old=states[i];bool contained=true,contains=true;
    for(int k=0;k<M*M && (contained||contains);k++){if(z[k]>old[k])contained=false;if(z[k]<old[k])contains=false;}
    if(contained){hits++;return true;}if(contains){states.RemoveAt(i);entries--;}
   }
  }else{states=new List<int[]>();memo.Add(key,states);}
  states.Add((int[])z.Clone());entries++;
  if(entries>=450000){memo.Clear();entries=0;}return false;
 }
 static bool Explore(int k,int mask){
  if((++nodes&1023)==0 && watch.Elapsed.TotalSeconds>=seconds){timeout=true;return false;}
  if(k==2*n){answer=(int[])steps.Clone();return true;}
  int[] z=layers[k];Wait(z);int pending=0,left=0,maxDeadline=-1;
  for(int c=0;c<m;c++){int id=occ[c],deadline=latest[c][remaining[c]];
   if(id>=0){
    pending++;
    if(!Tight(z,T,2+c,L+d+proc[id]+res[id]))return false;
    if(deadline<INF && (!Tight(z,T,0,deadline-S)||!Tight(z,2+c,0,deadline-S-P-d-L-proc[id])))return false;
   }else if(deadline<INF && !Tight(z,T,0,deadline))return false;
  }
  for(int i=0;i<n;i++)if((mask&(1<<i))!=0){left++;maxDeadline=Math.Max(maxDeadline,loadDue[i]);}
  if(left>0){int compulsory=left-1+Math.Max(0,pending+left-m);
   if(!Tight(z,T,0,maxDeadline-compulsory*S))return false;}
  ulong key=(uint)mask;for(int c=0;c<m;c++)key=(key<<5)|(uint)(occ[c]+1);
  if(Covered(z,key))return false;
  int[] w=layers[k+1];
  // Try transfers into empty chambers, then outbound transfers. Both orders are exhaustive.
  for(int i=0;i<n;i++)if((mask&(1<<i))!=0 && occ[chamber[i]]<0){
   int c=chamber[i];Array.Copy(z,w,M*M);
   if(!reverse && !Tight(w,T,0,due[i]-P))continue;
   Wait(w);
   int release=reverse ? -(latestV[i]+L+d+proc[i]+res[i]) : releaseV[i];
   if(!Tight(w,0,T,-release)||!Tight(w,T,0,reverse ? loadDue[i] : latestV[i]))continue;
   CopyClock(w,2+c);Shift(w);occ[c]=i;remaining[c]^=bit[i];steps[k]=2*i;
   if(Explore(k+1,mask^(1<<i)))return true;
   occ[c]=-1;remaining[c]^=bit[i];if(timeout)return false;
  }
  for(int c=0;c<m;c++){int i=occ[c];if(i<0)continue;
   Array.Copy(z,w,M*M);Wait(w);
   if(!Tight(w,2+c,T,-(P+d+L+proc[i]))||!Tight(w,T,2+c,L+d+proc[i]+res[i]))continue;
   if(reverse && (!Tight(w,0,T,-(-latestV[i]))||!Tight(w,T,0,-releaseV[i])))continue;
   Forget(w,2+c);Shift(w);
   if(reverse){Wait(w);if(!Tight(w,0,T,-(S-(due[i]-P))))continue;}
   occ[c]=-1;steps[k]=2*i+1;
   if(Explore(k+1,mask))return true;occ[c]=i;if(timeout)return false;
  }return false;
 }
 static void Main(string[] args){
  var a=Console.In.ReadToEnd().Split((char[])null,StringSplitOptions.RemoveEmptyEntries).Select(int.Parse).ToArray();
  int j=0;n=a[j++];m=a[j++];P=a[j++];L=a[j++];d=a[j++];q=a[j++];F=a[j++];S=P+2*d+L;
  if(m!=3 || n>25)throw new Exception("Domain");
  reverse=args.Length>1 && args[1]=="reverse";seconds=double.Parse(args[0],System.Globalization.CultureInfo.InvariantCulture);
  chamber=new int[n];proc=new int[n];ready=new int[n];due=new int[n];res=new int[n];hold=new int[n];first=new int[n];bit=new int[n];steps=new int[2*n];
  for(int i=0;i<n;i++){chamber[i]=a[j++];proc[i]=a[j++];ready[i]=a[j++];due[i]=a[j++];res[i]=a[j++];hold[i]=a[j++];first[i]=a[j++];}
  releaseV=new int[n];latestV=new int[n];loadDue=new int[n];int horizon=0;
  for(int i=0;i<n;i++){
   releaseV[i]=Math.Max(Math.Max(0,Math.Max(first[i],ready[i])),chamber[i]==F?q-P-d:0);
   latestV[i]=due[i]-P+hold[i]-d-L;
   loadDue[i]=reverse ? -releaseV[i]-P-d-L-proc[i] : due[i]-P;
   horizon=Math.Max(horizon,latestV[i]+L+d+proc[i]+res[i]);}
  latest=new int[m][];initMasks=new int[m];occ=Enumerable.Repeat(-1,m).ToArray();
  for(int c=0;c<m;c++){
   var ids=Enumerable.Range(0,n).Where(i=>chamber[i]==c).OrderBy(i=>loadDue[i]+2*S+proc[i]-d).ToArray();
   latest[c]=new int[1<<ids.Length];latest[c][0]=INF;initMasks[c]=latest[c].Length-1;
   for(int k=0;k<ids.Length;k++){int i=ids[k];bit[i]=1<<k;}
   for(int b=1;b<latest[c].Length;b++){int k=0;while((b&(1<<k))==0)k++;int i=ids[k],next=b^(1<<k);
    latest[c][b]=Math.Min(loadDue[i],latest[c][next]-(2*S+proc[i]-d));}
  }
  remaining=(int[])initMasks.Clone();layers=new int[2*n+1][];for(int k=0;k<layers.Length;k++)layers[k]=new int[M*M];
  var z=layers[0];for(int a1=0;a1<M;a1++)for(int b=0;b<M;b++)z[a1*M+b]=a1==b?0:INF;z[T*M]=reverse?-horizon:0;z[T]=-z[T*M];
  watch=Stopwatch.StartNew();bool hit=Explore(0,(1<<n)-1);
  Console.WriteLine((hit?"FEASIBLE":timeout?"UNKNOWN":"INFEASIBLE")+" "+nodes+" "+hits+" "+watch.Elapsed.TotalSeconds.ToString(System.Globalization.CultureInfo.InvariantCulture));
  if(hit)Console.WriteLine(string.Join(" ",reverse?answer.Reverse().Select(x=>x^1):answer.AsEnumerable()));
 }
}
