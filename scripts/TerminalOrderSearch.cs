// Optional offline witness constructor on the uniform terminal domain.
// A score is never an upper bound or an infeasibility certificate.
using System;
using System.Diagnostics;
using System.IO;
using System.Linq;

class TerminalOrderSearch {
    static int n, pick, place, travel, failed, repair;
    static int[,] duration;
    static int[] ready,due,residence,holding,first,chosen,trialChosen,order,trial,bestOrder,bestChosen;
    static int[] inside,finish,buffer;
    static Random rng;
    static double Score(int[] sequence,int[] dest) {
        Array.Clear(inside,0,inside.Length);
        int clock=0, late=0, maxLate=0, last=0;
        for(int k=0;k<sequence.Length;k++){
            int m=sequence[k],i=m/2,c=dest[i],a,b,violation;
            if(m%2==0){
                if(inside[c]!=0) return 1e8;
                inside[c]=i+1;
                a=Math.Max(clock,Math.Max(ready[i],k==0?first[i]:0));
                b=Math.Max(a+pick+travel,c==failed?repair:0);
                a=Math.Max(a,b+place-pick-holding[i]);
                violation=Math.Max(0,a+pick-due[i]);
                last=a; finish[i]=b+place+duration[i,c];
            } else {
                if(inside[c]!=i+1) return 1e8;
                inside[c]=0;
                a=Math.Max(clock,finish[i]);
                violation=Math.Max(0,a+pick-finish[i]-residence[i]);
                b=a+pick+travel;
            }
            late+=violation; maxLate=Math.Max(maxLate,violation);
            clock=b+place+travel;
        }
        // All tie breaks together stay below one tick of window violations on the study clocks.
        return late+0.18*maxLate+0.0001*last+0.00001*clock;
    }
    static void Mutate(){
        int m=order.Length, op=rng.Next(100),i=rng.Next(n),j=rng.Next(n);
        if(op<40){
            int a=rng.Next(m),b=Math.Max(0,Math.Min(m-1,a+rng.Next(-4,5)));
            int v=trial[a]; if(a==b) return;
            if(a<b) Array.Copy(trial,a+1,trial,a,b-a); else Array.Copy(trial,b,trial,b+1,a-b);
            trial[b]=v;
        } else if(op<66){
            int ci=chosen[i],cj=chosen[j];
            if(duration[i,cj]<0 || duration[j,ci]<0)return;
            for(int k=0;k<m;k++){
                int w=order[k]/2;
                if(w==i || w==j)trial[k]=2*(w==i?j:i)+order[k]%2;
            }
            trialChosen[i]=cj; trialChosen[j]=ci;
        } else {
            int c=rng.Next(inside.Length);
            if(duration[i,c]<0)c=chosen[i];
            int len=0;
            foreach(int x in order)if(x/2!=i)buffer[len++]=x;
            int a=rng.Next(len+1),b=a+rng.Next(Math.Min(7,len-a)+1);
            int k2=0;
            for(int k=0;k<=len;k++){
                if(k==a)trial[k2++]=2*i;
                if(k==b)trial[k2++]=2*i+1;
                if(k<len)trial[k2++]=buffer[k];
            }
            trialChosen[i]=c;
        }
    }
    static void Main(string[] args){
        int[] data=(args[0]=="-" ? Console.In.ReadToEnd() : File.ReadAllText(args[0])).Split((char[])null,StringSplitOptions.RemoveEmptyEntries).Select(int.Parse).ToArray();
        int p=0; n=data[p++]; int nc=data[p++];pick=data[p++];place=data[p++];travel=data[p++];failed=data[p++];repair=data[p++];
        duration=new int[n,nc];ready=new int[n];due=new int[n];residence=new int[n];holding=new int[n];first=new int[n];
        chosen=new int[n];trialChosen=new int[n];bestChosen=new int[n]; order=new int[2*n];trial=new int[2*n];buffer=new int[2*n];bestOrder=new int[2*n];
        inside=new int[nc];finish=new int[n];rng=new Random(int.Parse(args[2]));
        for(int i=0;i<n;i++){
            ready[i]=data[p++];due[i]=data[p++];residence[i]=data[p++];holding[i]=data[p++];first[i]=data[p++];
            for(int c=0;c<nc;c++)duration[i,c]=data[p++];
        }
        for(int i=0;i<n;i++){while(duration[i,chosen[i]]<0)chosen[i]++;order[2*i]=2*i;order[2*i+1]=2*i+1;}
        double score=Score(order,chosen), best=score;long steps=0;
        Array.Copy(order,bestOrder,2*n);Array.Copy(chosen,bestChosen,n);
        var watch=Stopwatch.StartNew();
        double budget=double.Parse(args[1],System.Globalization.CultureInfo.InvariantCulture);
        while(watch.Elapsed.TotalSeconds<budget && best>=1){
            Array.Copy(bestOrder,order,2*n);Array.Copy(bestChosen,chosen,n); score=best;
            double temp=2+6*rng.NextDouble();
            for(int it=0;it<50000 && best>=1;it++,steps++){
                Array.Copy(order,trial,2*n);Array.Copy(chosen,trialChosen,n);Mutate();
                double candidate=Score(trial,trialChosen);
                if(candidate<=score || rng.NextDouble()<Math.Exp((score-candidate)/temp)){
                    score=candidate;int[] swap=order;order=trial;trial=swap;swap=chosen;chosen=trialChosen;trialChosen=swap;
                    if(score<best){
                        best=score;Array.Copy(order,bestOrder,2*n);Array.Copy(chosen,bestChosen,n);
                    }
                }
                temp*=0.99994;
            }
        }
        Console.WriteLine(string.Join(" ",bestOrder));Console.WriteLine(string.Join(" ",bestChosen));
        Console.WriteLine(steps+" "+best.ToString(System.Globalization.CultureInfo.InvariantCulture));
    }
}
