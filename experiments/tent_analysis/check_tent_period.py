"""Clean-room analysis of Nardo et al.2023 Fig2, K=32.
No author RTL copied. Bit vector b1 is the MSB; bk is the LSB.
Run: python3 check_tent_period.py. Requires SymPy for polynomial validation.
This analyzes the exact recurrence, not the full PSO consumer or FPGA timing.
"""
from pathlib import Path
import json, math
import sympy as sp

K=32
MASK=(1<<K)-1

def transition(state,k=K):
    mask=(1<<k)-1
    complemented=state ^ (mask if (state>>(k-1))&1 else 0)
    return ((complemented<<1)&mask) | (((state>>1)^state)&1)

def polynomial_mod(a,b):
    while a.bit_length()>=b.bit_length():
        a ^= b<<(a.bit_length()-b.bit_length())
    return a

def polynomial_mul_mod(a,b,m):
    out=0
    while b:
        if b&1:out^=a
        a<<=1
        b>>=1
    return polynomial_mod(out,m)

def polynomial_power_mod(a,n,m):
    out=1
    while n:
        if n&1:out=polynomial_mul_mod(out,a,m)
        a=polynomial_mul_mod(a,a,m)
        n>>=1
    return out

def gf2_rank(columns):
    pivots={}
    for v in columns:
        while v:
            i=v.bit_length()-1
            if i in pivots:v^=pivots[i]
            else:
                pivots[i]=v
                break
    return len(pivots)

z=sp.symbols('z')
columns=[transition(1<<j) for j in range(K)]
A=sp.Matrix(K,K,lambda i,j:(columns[j]>>i)&1)
characteristic=sp.Poly(A.charpoly(z).as_expr(),z,modulus=2)
unit,factors=sp.factor_list(characteristic)
report={
 'source_doi':'10.3390/electronics12081953',
 'source_locator':'Fig2, Sec3.1; K32 recurrence adaptation',
 'precision':K,
 'recurrence':'next={x[K-2:0] XOR repeat(x[K-1],K-1), x[1] XOR x[0]}',
 'gf2_rank':gf2_rank(columns),
 'characteristic_polynomial':str(characteristic.as_expr()),
 'factors':[],
 'scope':'Exact state-transition analysis; byte-adapter period is at most state period; no security or independence claim'
}
orders=[]
for f,multiplicity in factors:
    assert multiplicity==1
    assert f.is_irreducible
    entry={'polynomial':str(f.as_expr()),'degree':f.degree(),'multiplicity':multiplicity}
    if f.as_expr()==z:
        entry['kind']='one-step transient factor'
    else:
        bits=sum((int(c)%2)<<int(e[0]) for e,c in f.terms())
        candidate=(1<<f.degree())-1
        order=candidate
        for prime in sp.factorint(candidate):
            while order%prime==0 and polynomial_power_mod(2,order//prime,bits)==1:
                order//=prime
        assert polynomial_power_mod(2,order,bits)==1
        for prime in sp.factorint(order):
            assert polynomial_power_mod(2,order//prime,bits)!=1
        entry['multiplicative_order']=order
        orders.append(order)
    report['factors'].append(entry)

bound=math.lcm(*orders)
report['every_eventual_state_period_divides']=bound
report['maximum_transient_steps']=1
stable_seed=transition(1)
x=transition(stable_seed)
period=1
while x!=stable_seed:
    x=transition(x)
    period+=1
    assert period<=bound
assert period==bound
report['direct_cycle_check']={'seed':1,'tail_steps':1,'first_stable_state':hex(stable_seed),'exact_period':period}
report['absorbing_examples']={'zero_to':transition(0),'all_ones_to':transition(MASK)}
for i in range(1,100):
    assert transition(i)==transition(i^MASK)
report['complement_coalescence']='f(x)=f(bitwise_complement(x)), follows algebraically from Fig2 recurrence;100 examples checked'
out=Path(__file__).with_name('tent32_period.json')
out.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
