using System;
using System.IO;
using System.IO.MemoryMappedFiles;
using System.Linq;
using System.Diagnostics;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;

unsafe class BackHull {
 const int R=5,M=6,T=1,INF=10000000;
 static int n,C,P,L,D,S,Q,F,N,full,horizon,knownForward,maxLayer,maxStates,split;static int[] chan,pr,first,du,release,latest,lo,hi,cm,bit,tail;
 static byte* table;static MemoryMappedFile mf;static MemoryMappedViewAccessor view;static long nodes;
 static int[] buffer=new int[M*M];

 static bool Bound(int[] z,int x,int y,int v){
  if(z[x*M+y]<=v)return true;if(z[y*M+x]+v<0)return false;
  fixed(int* p=z){
   int* rowY=p+y*M;for(int i=0;i<M;i++){int* row=p+i*M;int a=row[x];if(a==INF)continue;
    int av=a+v;for(int j=0;j<M;j++){int b=rowY[j];if(b!=INF&&av+b<row[j])row[j]=av+b;}
   }
  }return true;
 }
 static void Drop(int[] z,int c){for(int i=0;i<M;i++)if(c!=i)z[c*M+i]=z[i*M+c]=INF;z[c*M+c]=0;}
 static void Copy(int[] z,int from,int to){for(int j=0;j<M;j++)if(j!=to){z[to*M+j]=z[from*M+j];z[j*M+to]=z[j*M+from];}z[to*M+to]=0;}
 static void BackShift(int[] z){for(int i=0;i<M;i++)if(i!=T){if(z[T*M+i]!=INF)z[T*M+i]-=S;if(z[i*M+T]!=INF)z[i*M+T]+=S;}}

 static int[][][] earliest;static int[][] countDone;static int[] offsetBit;
 static void InitEnergy(){
  debts=new int[3][][];earliest=new int[3][][];countDone=new int[3][];offsetBit=new int[3];
  for(int c=0;c<3;c++){
   int[] ids=Enumerable.Range(0,n).Where(i=>chan[i]==c).ToArray();int total=1<<ids.Length;
   int shift=0;if(ids.Length>0){int pos=ids.Min(i=>bit[i]);while((1<<shift)!=pos)shift++;}offsetBit[c]=shift;
   earliest[c]=new int[total][];debts[c]=new int[total][];countDone[c]=new int[total];
   for(int b=0;b<total;b++){
    var jobs=ids.Where(i=>(b&(bit[i]>>shift))!=0).ToArray();int t=jobs.Length;countDone[c][b]=t;
    var dp=new int[N+2];earliest[c][b]=dp;
    if(t==0){for(int k=0;k<dp.Length;k++)dp[k]=k*S;continue;}
    int g=jobs.Min(i=>release[i]);int debt=0,whole=0;
    var partial=new List<int>();
    foreach(int i in jobs){int lag=Math.Max(0,lo[i]-S);debt+=lag;whole+=lag/S;partial.Add(lag%S);}
    partial.Sort((x,y)=>y.CompareTo(x));int[] owed=new int[N+2];debts[c][b]=owed;owed[0]=debt;
    for(int v=1;v<owed.Length;v++)
     owed[v]=owed[v-1]-(v<=whole?S:v-whole<=partial.Count?partial[v-whole-1]:0);
    for(int k=2*t;k<dp.Length;k++){
     int f=k-2*t,best=INF;
     for(int before=0;before<=f;before++){
      int start=Math.Max(before*S,g);
      best=Math.Min(best,start+(k-before)*S+owed[f-before]);
     }
     dp[k]=best;
    }
   }
  }
 }

 // All e transfers before the first failing-chamber load are foreign. Even
 // starting at time zero their path to the endpoint incurs k*S plus unpaid
 // chamber-processing time. At gate R the same path also takes at least R-P-D
 // plus the remaining mandatory services and the unpaid processing.
 static bool GatePrefix(int[] z,int b,int k,int clock,int correction){
  if(b==0)return true;
  int free=k-2*countDone[F][b],max=z[clock*M]+correction;
  if(free<0)throw new Exception("prefix length");

  var unpaid=debts[F][b];int available=max-k*S;
  if(unpaid[free]>available)return false;
  int l=0,r=free;while(l<r){int mid=(l+r)>>1;if(unpaid[mid]<=available)r=mid;else l=mid+1;}
  int best=(k-free+l)*S+unpaid[l];return Bound(z,R,clock,P+D+correction-best);

 }
 static bool PrefixBounds(int[] z,int mask,int ac,int k){
  for(int c=0;c<3;c++){
   int b=(cm[c]&~mask)>>offsetBit[c];
   if((ac&(1<<c))==0){if(!Bound(z,0,T,-earliest[c][b][k]) || (c==F&&!GatePrefix(z,b,k,T,0)))return false;}
   else{
    if(b==0)return false;
    if(!Bound(z,0,2+c,S-earliest[c][b][k+1]) || (c==F&&!GatePrefix(z,b,k+1,2+c,S)))return false;
    // Remove only the current occupant's inbound transfer from this prefix.
    // Keep the other actions at their original times. They form a valid
    // relaxed prefix with k-1 transfers. The removed move need not be last.
    int lb=omit[c][b][k];
    if(!Bound(z,0,T,-lb))return false;
   }
  }
  return true;
 }

 static MemoryMappedFile pm;static MemoryMappedViewAccessor pv;static byte* pa;static int pdepth=-1;
 static void OpenParam(string original){
  if(original=="-")return;string path=Path.Combine(Path.GetDirectoryName(original),"param.bin");if(!File.Exists(path))return;
  pm=MemoryMappedFile.CreateFromFile(new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.Read),null,0,MemoryMappedFileAccess.Read,HandleInheritability.None,false);
  pv=pm.CreateViewAccessor(0,0,MemoryMappedFileAccess.Read);pv.SafeMemoryMappedViewHandle.AcquirePointer(ref pa);
  if(pv.ReadInt32(0)!=0x57524731||pv.ReadInt32(4)!=n||pv.ReadInt32(8)>Q)throw new Exception("param scope");
  for(int i=0;i<32;i++)if(pa[64+i]!=table[64+i])throw new Exception("param input signature");
  for(int i=0;i<n;i++)if(bit[i]!=pv.ReadInt32(144+4*i))throw new Exception("param job encoding");pdepth=pv.ReadInt32(12);
 }
 static bool ParamTest(int[] z,int key,int k,int ac){
  if(k>pdepth)return true;short* p=(short*)(pa+4096L+16L*key);
  if(p[0]==0)return false;
  if(p[1]!=32767&&!Bound(z,R,0,p[1]))return false;
  if(p[2]!=32767&&!Bound(z,R,T,p[2]))return false;
  for(int c=0;c<3;c++)if((ac&(1<<c))!=0&&p[3+c]!=32767&&!Bound(z,R,2+c,p[3+c]))return false;
  return true;
 }
 static bool Admit(int[] z,int mask,int ac,int k){
  if(!ParamTest(z,(mask<<3)|ac,k,ac)||!Bound(z,0,T,-k*S)||!SuffixTest(z,mask,ac,k)||!PrefixBounds(z,mask,ac,k))return false;
  byte* row=table+4096L+16L*((mask<<3)|ac);
  if(k<=knownForward){
   if(row[0]==0 || !Bound(z,0,T,-(k*S+row[0]-1)))return false;
   for(int c=0;c<3;c++)if((ac&(1<<c))!=0){
    int v=2+c;
    if(!Bound(z,0,v,-(k*S+row[1+c]-1)))return false;
    if(row[4+c]!=255&&!Bound(z,v,T,row[4+c]))return false;
    if(row[7+c]!=255&&!Bound(z,v,0,k*S+row[7+c]))return false;
   }
   int j=10;for(int c=0;c<3;c++)for(int e=0;e<3;e++)if(c!=e){
    int v=row[j++];if(v<255 && (ac&(1<<c))!=0 && (ac&(1<<e))!=0 && !Bound(z,2+c,2+e,v-127))return false;
   }
  }
  for(int c=0;c<3;c++)if((ac&(1<<c))!=0 && !Bound(z,T,2+c,0))return false;
  return true;
 }

 static int[] forced,suffix;
 static bool Allowed(int k,int m){
  if(forced!=null&&forced[k-1]!=m)return false;
  int j=N-k;return suffix==null||j>=suffix.Length||suffix[j]==m;
 }
static int opt=-1,cap;static int[][][] debts;static int[] counts;static int bins;static int[] rankLag=new int[3];

 static int[][] suffixLimit,maximumDue;static int[][][] omit;static int openingCap;
 static void SuffixData(){
  suffixLimit=new int[3][];maximumDue=new int[3][];omit=new int[3][][];
  for(int c=0;c<3;c++){
   int[] ids=Enumerable.Range(0,n).Where(i=>chan[i]==c).OrderBy(i=>i==tail[c]?INF:du[i]-P+S+Math.Max(S,lo[i])).ToArray();
   int num=1<<ids.Length;suffixLimit[c]=new int[num];maximumDue[c]=new int[num];omit[c]=new int[num][];
   for(int sub=0;sub<num;sub++){int total=0,ub=INF;
    foreach(int i in ids)if((sub&(bit[i]>>offsetBit[c]))!=0){
     ub=Math.Min(ub,du[i]-P-total);total+=S+Math.Max(S,lo[i]);
    }suffixLimit[c][sub]=ub;
    int last=-INF;foreach(int i in ids)if((sub&(bit[i]>>offsetBit[c]))!=0)last=Math.Max(last,du[i]-P);maximumDue[c][sub]=last;
    var skip=new int[N+1];omit[c][sub]=skip;
    for(int k=1;k<=N;k++){int value=INF;for(int jj=sub;jj>0;jj&=jj-1)value=Math.Min(value,earliest[c][sub^(jj&-jj)][k-1]);skip[k]=value;}

   }
  }
  int all=cm[F]>>offsetBit[F];openingCap=-INF;
  for(int i=0;i<n;i++)if(chan[i]==F && (i!=tail[F]||countDone[F][all]==1)){
   int rest=all^(bit[i]>>offsetBit[F]);
   openingCap=Math.Max(openingCap,Math.Min(latest[i],suffixLimit[F][rest]-S-Math.Max(S,lo[i]))+P+D);
  }

 }
 static bool SuffixTest(int[] z,int mask,int ac,int k){
  int left=0,big=-INF;
  for(int c=0;c<3;c++){
   int b=(cm[c]&mask)>>offsetBit[c];if(b==0)continue;
   int lim=suffixLimit[c][b];int occ=(ac>>c)&1;
   if(!Bound(z,T,0,lim-occ*S)||(occ!=0&&!Bound(z,2+c,0,lim-S)))return false;
   if(c==F && (cm[c]&mask)==cm[c] && !Bound(z,R,0,openingCap))return false;
   big=Math.Max(big,maximumDue[c][b]);
   left+=countDone[c][b];
  }
  if(left>0){
   int active=(ac&1)+((ac>>1)&1)+((ac>>2)&1);
   if(!Bound(z,T,0,big-S*(left-1+Math.Max(0,left+active-3))))return false;
  }
  return true;
 }

 struct Envelope{public int minT,minU,maxU,maxUT,maxR,maxRT,maxRU;}
 static Dictionary<int,Envelope>[] ageCache={new Dictionary<int,Envelope>(),new Dictionary<int,Envelope>(),new Dictionary<int,Envelope>()};
 static Envelope Ages(int c,int b,int k,int h){
  int key=((b*52+k)<<4)|h;Envelope x;if(ageCache[c].TryGetValue(key,out x))return x;
  x=new Envelope{minT=INF,minU=INF,maxU=-INF,maxUT=-INF,maxR=-INF,maxRT=-INF,maxRU=-INF};
  for(int i=0;i<n;i++)if(chan[i]==c && (b&(bit[i]>>offsetBit[c]))!=0){
   int ib=bit[i]>>offsetBit[c],prior=b^ib,ct=countDone[c][prior];
   // An occupied wafer was loaded age moves ago and cannot be unloaded
   // earlier than h moves after the current clock. Rank bounds ignore idle.
   for(int age=1;age<=Math.Min(k,hi[i]/S-h);age++){
    int u=k-age,foreign=u-2*ct;if(foreign<0)continue;
    int pre=earliest[c][prior][u],duePick=du[i]-P;
    if(pre>duePick)continue;
    int earliestVirtual=Math.Max(pre,release[i]),rmax=INF,rt=INF,ru=INF;
    if(c==F){
     int rv=P+D; // R - virtual, if this is the first load of F
     if(prior!=0){
      int cost=INF;var debt=debts[c][prior];
      for(int e=0;e<=foreign;e++)if(u*S+debt[foreign-e]<=duePick)
       cost=Math.Min(cost,(u-e)*S+debt[foreign-e]);
      if(cost==INF)continue;
      rv=P+D-cost;rmax=duePick+rv;
     }
     if(rmax<Q)continue;
     earliestVirtual=Math.Max(earliestVirtual,Q-rv);rt=rv-age*S;ru=rv-lo[i];
    }
    if(earliestVirtual>latest[i])continue;
    x.minT=Math.Min(x.minT,earliestVirtual+age*S);
    x.minU=Math.Min(x.minU,earliestVirtual+Math.Max(lo[i],(age+h)*S));
    x.maxU=Math.Max(x.maxU,latest[i]+hi[i]);x.maxUT=Math.Max(x.maxUT,hi[i]-age*S);
    x.maxR=Math.Max(x.maxR,rmax);x.maxRT=Math.Max(x.maxRT,rt);x.maxRU=Math.Max(x.maxRU,ru);
   }
  }ageCache[c].Add(key,x);return x;
 }
 static bool AgeTest(int[] z,int c,int mask,int k,int h){
  var e=Ages(c,(cm[c]&~mask)>>offsetBit[c],k,h);int v=2+c;
  if(e.minT==INF || !Bound(z,0,T,-e.minT)||!Bound(z,0,v,-e.minU)||!Bound(z,v,0,e.maxU)||!Bound(z,v,T,e.maxUT))return false;
  if(c==F && (!Bound(z,R,0,e.maxR)||!Bound(z,R,T,e.maxRT)||!Bound(z,R,v,e.maxRU)))return false;
  return true;
 }
 static bool OrderBounds(int[] z,int mask,int ac,int encoded,int k){
  for(int c=0;c<3;c++)rankLag[c]=(encoded>>(4*c))&15;
  for(int c=0;c<3;c++)if((ac&(1<<c))!=0){
   int h=rankLag[c];if(!AgeTest(z,c,mask,k,h))return false;if(!Bound(z,T,2+c,-h*S))return false;
   for(int j=0;j<3;j++)if(c!=j&&(ac&(1<<j))!=0){
    int later=rankLag[j];
    if(later==h && h<bins)return false;
    if(later>h && !Bound(z,2+c,2+j,-(later-h)*S))return false;
   }
  }
  return true;
 }
 static int Advance(int ac,int encoded,int skip){
  int v=0;for(int c=0;c<3;c++)if(c!=skip && (ac&(1<<c))!=0)
   v|=Math.Min(bins,1+((encoded>>(4*c))&15))<<(4*c);
  return v;
 }
 static void Add(Dictionary<long,int[]> next,int mask,int ac,int encoded,int[] z,int k){
  if(!Admit(z,mask,ac,k)||!OrderBounds(z,mask,ac,encoded,k))return;
  long key=((long)((mask<<3)|ac)<<12)|((long)encoded);
  int[] old;if(next.TryGetValue(key,out old)){for(int i=0;i<M*M;i++)old[i]=Math.Max(old[i],z[i]);}
  else next.Add(key,(int[])z.Clone());
 }
 static string Run(double budget){
  var time=Stopwatch.StartNew();int[] z0=new int[M*M];for(int i=0;i<M*M;i++)z0[i]=i%(M+1)==0?0:INF;
  Bound(z0,0,R,-Q);Bound(z0,R,0,cap);Bound(z0,T,0,horizon+S);Bound(z0,0,T,-N*S);var cur=new Dictionary<long,int[]>();cur.Add(0,z0);
  for(int k=N;k>=0;k--){
   if(cur.Count==0)return "INFEASIBLE";var next=new Dictionary<long,int[]>();maxLayer=Math.Max(maxLayer,cur.Count);
   foreach(var kv in cur){
    if((++nodes&1023)==0 && (time.Elapsed.TotalSeconds>budget||next.Count>maxStates))return "UNKNOWN";
    int key=(int)(kv.Key>>12),mask=key>>3,ac=key&7,encoded=(int)(kv.Key&4095);int[] z=kv.Value;
    if(!Admit(z,mask,ac,k)||!OrderBounds(z,mask,ac,encoded,k))continue;
    if(k==0){if(mask==full&&ac==0&&Bound(z,T,0,0))opt=Math.Max(opt,z[R*M]);continue;}
    for(int c=0;c<C;c++){
     int v=c+2;
     if((ac&(1<<c))==0){
      // Undo an outbound. Its start instant was exactly post-T minus S.
      if((cm[c]&~mask)==0 || !Allowed(k,-1-c))continue;
      Array.Copy(z,buffer,M*M);BackShift(buffer);Copy(buffer,T,v);Drop(buffer,T);
      if(Bound(buffer,T,v,0))Add(next,mask,ac|(1<<c),Advance(ac,encoded,c),buffer,k-1);
     }else{
      // Undo an inbound. Identity is chosen at this point. All previous
      // source pickups are still represented in the unstarted mask.
      for(int i=0;i<n;i++)if(chan[i]==c && (mask&bit[i])==0){
       if(!Allowed(k,i) || (tail[c]>=0 && (((cm[c]&mask)==0)!=(i==tail[c]))))continue;
       Array.Copy(z,buffer,M*M);BackShift(buffer);
       if(c==F && !Bound(buffer,R,T,P+D))continue;
       if(!Bound(buffer,0,T,-release[i]) || !Bound(buffer,T,0,latest[i]))continue;
       if(!Bound(buffer,T,v,-lo[i]) || !Bound(buffer,v,T,hi[i]))continue;
       Drop(buffer,v);
       // Downward closure of T projects out the virtual input start. An
       // earlier free robot may pick before the source deadline and wait.
       for(int j=0;j<M;j++)if(j!=T)buffer[j*M+T]=INF;
       if(Bound(buffer,T,0,du[i]-P))Add(next,mask|bit[i],ac^(1<<c),Advance(ac,encoded,c),buffer,k-1);
      }
     }
    }
   }
   Console.WriteLine(k+" "+cur.Count+" "+next.Count+" "+time.Elapsed.TotalSeconds);cur=next;
  }return opt>=Q?"UPPER":"INFEASIBLE";
 }
 static void Main(string[] args){
  var a=Console.In.ReadToEnd().Split((char[])null,StringSplitOptions.RemoveEmptyEntries).Select(int.Parse).ToArray();int j=0;
  n=a[j++];C=a[j++];P=a[j++];L=a[j++];D=a[j++];Q=a[j++];F=a[j++];S=P+L+2*D;N=2*n;full=(1<<n)-1;
  if(n>24||C!=3)throw new Exception("domain");

  if(args[0]=="-"){
   knownForward=-1;bit=new int[n];int shift=0;
   for(int c=0;c<3;c++)for(int i=0;i<n;i++)if(a[7+7*i]==c)bit[i]=1<<shift++;
   if(shift!=n)throw new Exception("room id");
  }else{
  mf=MemoryMappedFile.CreateFromFile(new FileStream(args[0],FileMode.Open,FileAccess.Read,FileShare.Read),null,0,MemoryMappedFileAccess.Read,HandleInheritability.None,false);
  view=mf.CreateViewAccessor(0,0,MemoryMappedFileAccess.Read);view.SafeMemoryMappedViewHandle.AcquirePointer(ref table);
  if(view.ReadInt32(0)!=0x57484C32||view.ReadInt32(4)!=n||view.ReadInt32(8)>Q)throw new Exception("lookup scope");
  int[] sig=(int[])a.Clone();sig[5]=0;var digest=SHA256.Create().ComputeHash(Encoding.ASCII.GetBytes(string.Join(" ",sig)));
  for(int x=0;x<32;x++)if(digest[x]!=table[64+x])throw new Exception("route signature");
  knownForward=view.ReadInt32(12);bit=new int[n];view.ReadArray(144,bit,0,n);
  }
  chan=new int[n];pr=new int[n];first=new int[n];du=new int[n];release=new int[n];latest=new int[n];lo=new int[n];hi=new int[n];cm=new int[3];
  for(int i=0;i<n;i++){
   int c=a[j++];chan[i]=c;cm[c]|=bit[i];pr[i]=a[j++];int ready=a[j++];du[i]=a[j++];int res=a[j++],hold=a[j++];first[i]=a[j++];
   release[i]=Math.Max(Math.Max(0,Math.Max(ready,first[i])),c==F?Q-P-D:0);
   latest[i]=du[i]-P+hold-D-L;lo[i]=P+D+L+pr[i];hi[i]=D+L+pr[i]+res;
   horizon=Math.Max(horizon,latest[i]+hi[i]);
  }
  tail=args[1].Split(',').Select(int.Parse).ToArray();maxStates=int.Parse(args[2]);bins=int.Parse(args[3]);if(bins<0||bins>=15)throw new ArgumentException();
  cap=int.Parse(args[5]);if(cap<Q)throw new Exception("gate interval");if(args.Length>6 && args[6].StartsWith("prefix=")){
   var v=args[6].Substring(7);suffix=v=="-"?new int[0]:v.Split(',').Select(int.Parse).ToArray();
  }else if(args.Length>6)forced=File.ReadAllText(args[6]).Split((char[])null,StringSplitOptions.RemoveEmptyEntries).Select(int.Parse).Select(x=>x%2==0?x/2:-1-chan[x/2]).ToArray();OpenParam(args[0]);InitEnergy();SuffixData();string result=Run(double.Parse(args[4],System.Globalization.CultureInfo.InvariantCulture));
  Console.WriteLine("RESULT "+result+" "+nodes+" "+maxLayer+" "+opt);
 }
}