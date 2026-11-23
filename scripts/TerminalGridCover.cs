// Constructive terminal grid cover. Incomplete search has no infeasibility semantics.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;

sealed class Cover {
    readonly int[] left,right,up,down,column,count,row;
    int next,nodes;
    public readonly List<int> Selected=new List<int>();
    public Cover(int primary,int total,int entries) {
        int capacity=total+entries+1;
        left=new int[capacity]; right=new int[capacity]; up=new int[capacity];
        down=new int[capacity]; column=new int[capacity]; row=new int[capacity];
        count=new int[total+1]; next=total+1;
        for(int h=0;h<=total;h++) {
            left[h]=right[h]=up[h]=down[h]=h;
            if(h<=primary){left[h]=(h+primary)%(primary+1);right[h]=(h+1)%(primary+1);}
        }
    }
    public void Add(int id,int[] columns) {
        int first=next;
        foreach(int c in columns) {
            int x=next++;
            column[x]=c; row[x]=id; count[c]++;
            up[x]=up[c];down[x]=c;down[up[c]]=x;up[c]=x;
            left[x]=x-1;right[x]=x+1;
        }
        left[first]=next-1;right[next-1]=first;
    }
    void Hide(int c) {
        right[left[c]]=right[c];left[right[c]]=left[c];
        for(int i=down[c];i!=c;i=down[i])
            for(int j=right[i];j!=i;j=right[j]){
                down[up[j]]=down[j];up[down[j]]=up[j];count[column[j]]--;
            }
    }
    void Restore(int c) {
        for(int i=up[c];i!=c;i=up[i])
            for(int j=left[i];j!=i;j=left[j]){
                count[column[j]]++;down[up[j]]=j;up[down[j]]=j;
            }
        right[left[c]]=c;left[right[c]]=c;
    }
    public bool Find(Stopwatch timer,int milliseconds,int limit) {
        if(right[0]==0)return true;
        if(++nodes>limit || timer.ElapsedMilliseconds>=milliseconds)return false;
        int c=right[0];
        for(int j=right[c];j!=0;j=right[j]) if(count[j]<count[c])c=j;
        if(count[c]==0)return false;
        Hide(c);
        for(int i=down[c];i!=c && nodes<=limit;i=down[i]){
            Selected.Add(row[i]);
            for(int j=right[i];j!=i;j=right[j])Hide(column[j]);
            if(Find(timer,milliseconds,limit))return true;
            for(int j=left[i];j!=i;j=left[j])Restore(column[j]);
            Selected.RemoveAt(Selected.Count-1);
        }
        Restore(c);
        return false;
    }
}

class TerminalGridCover {
    struct Option { public int job,c,u,v; public int[] columns; }
    static void Main(string[] args) {
        var timer=Stopwatch.StartNew();
        int milliseconds=int.Parse(args[0]);
        int[] raw=Console.In.ReadToEnd().Split((char[])null,StringSplitOptions.RemoveEmptyEntries).Select(int.Parse).ToArray();
        int n=raw[0], nc=raw[1],P=raw[2],L=raw[3],d=raw[4],F=raw[5],q=raw[6],stride=5+nc;
        int last=-1; int[] data=raw.Skip(7).ToArray();
        for(int i=0;i<n;i++) if(Enumerable.Range(0,nc).All(c=>c==F || data[i*stride+5+c]<0)) {
            if(last>=0)return;
            last=i;
        }
        if(last<0 || n<2 || q<=0)return;
        int m=2*(n-1), period=P+L+2*d, first=int.MaxValue,deadline=data[last*stride+1];
        for(int i=0;i<n;i++) if(i!=last)first=Math.Min(first,Math.Max(data[i*stride],data[i*stride+4]));
        int slack=deadline-P-m*period-first;
        if(slack<0 || q+L>deadline+data[last*stride+3])return;
        var rng=new Random(571);
        for(int attempt=0;timer.ElapsedMilliseconds<milliseconds;attempt++) {
            int[] idle=new int[m],clock=new int[m];
            int span=attempt==0?0:(attempt==2?slack/2:slack);
            if(attempt<3)for(int k=0;k<m;k++)idle[k]=span*k/(m-1);
            else if(attempt%3!=0) {
                int parts=rng.Next(1,6);
                for(int part=0;part<parts;part++){
                    int start=rng.Next(1,m),value=(span*(part+1)/parts)-(span*part/parts);
                    for(int k=start;k<m;k++)idle[k]+=value;
                }
            } else { for(int k=0;k<m;k++)idle[k]=rng.Next(span+1);Array.Sort(idle); }
            for(int k=0;k<m;k++)clock[k]=first+k*period+idle[k];
            var options=new List<Option>();int entries=0;
            int primary=m+n-1;
            for(int i=0;i<n;i++)if(i!=last) {
                int off=i*stride, j=i<last?i:i-1;
                for(int c=0;c<nc;c++) {
                    int t=data[off+5+c];
                    if(t<0 || data[off+3]<L+d)continue;
                    for(int u=0;u<m-1;u++){
                        int b=clock[u]+P+d;
                        if(clock[u]<Math.Max(data[off],data[off+4]) || clock[u]+P>data[off+1] || (c==F && b<q))continue;
                        for(int v=u+1;v<m && clock[v]+P<=b+L+t+data[off+2];v++){
                            if(clock[v]<b+L+t)continue;
                            int[] cols=new int[3+v-u];cols[0]=u+1;cols[1]=v+1;cols[2]=m+j+1;
                            for(int k=u;k<v;k++)cols[3+k-u]=primary+1+c*m+k;
                            options.Add(new Option{job=i,c=c,u=u,v=v,columns=cols});entries+=cols.Length;
                        }
                    }
                }
            }
            var cover=new Cover(primary,primary+nc*m,entries);
            for(int i=options.Count-1;i>0;i--){int j=rng.Next(i+1);var tmp=options[i];options[i]=options[j];options[j]=tmp;}
            for(int i=0;i<options.Count;i++)cover.Add(i,options[i].columns);
            if(!cover.Find(timer,milliseconds,attempt%5==4?12000:900))continue;
            int[] seq=new int[2*n],chambers=new int[n];
            foreach(int index in cover.Selected){
                Option o=options[index];seq[o.u]=2*o.job;seq[o.v]=2*o.job+1;chambers[o.job]=o.c;
            }
            seq[m]=2*last;seq[m+1]=2*last+1;chambers[last]=F;
            Console.WriteLine(string.Join(" ",seq));Console.WriteLine(string.Join(" ",chambers));return;
        }
    }
}
