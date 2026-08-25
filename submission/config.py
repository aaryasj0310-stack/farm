"""Submission configuration and pre-calibrated trace matrix (v1.32.7 compatible)."""

import base64
import json
import zlib

TURNS_PER_DAY = 24
SEASON_DAYS = 30
EPISODE_STEPS = 720
BOARD_SIZE = 10
SHED_CAPACITY = 100
MAX_MARKET_ORDERS = 10
SHED_ACCESS_TILES = [(4, 4), (5, 4), (4, 5), (5, 5)]

PRODUCTS = {
    "WHEAT", "CARROT", "TOMATO", "STRAWBERRY", "MELON",
    "EGG", "MILK", "WOOL", "FERTILIZER",
}

SELL_TIE_PRIORITY = {
    "WOOL": 8, "MELON": 7, "MILK": 6, "STRAWBERRY": 5,
    "CARROT": 4, "FERTILIZER": 3, "WHEAT": 2, "EGG": 1,
}

NON_SELL_PRIORITY = {
    "HIRE": 0,
    "BUY_ANIMAL": 1,
    "BUY_LAND": 2,
    "BUY_SEED": 3,
    "BUY_PRODUCT": 4,
}

CROPS = {
    "WHEAT":      dict(seed=10,  first_yield_day=2,  max_yield_day=4,  interval=0, max_yield=6, ongoing=False, window_start=2),
    "CARROT":     dict(seed=20,  first_yield_day=2,  max_yield_day=3,  interval=0, max_yield=4, ongoing=False, window_start=2),
    "TOMATO":     dict(seed=50,  first_yield_day=8,  max_yield_day=8,  interval=1, max_yield=4, ongoing=True),
    "STRAWBERRY": dict(seed=100, first_yield_day=10, max_yield_day=10, interval=2, max_yield=4, ongoing=True),
    "MELON":      dict(seed=80,  first_yield_day=10, max_yield_day=12, interval=0, max_yield=6, ongoing=False, window_start=6),
}

ANIMALS = {
    "GOOSE": dict(cost=300, structure="COOP",    first_yield_day=4, interval=1, max_held=4, product="EGG"),
    "COW":   dict(cost=400, structure="PASTURE", first_yield_day=8, interval=2, max_held=6, product="MILK"),
    "SHEEP": dict(cost=500, structure="PASTURE", first_yield_day=6, interval=3, max_held=6, product="WOOL"),
}

MARKET_I0 = 10000
PRICE_FLOOR = 1
MARKET_PARAMS = {
    "WHEAT":      {"base": 25,  "T": 400, "bf": "sqrt",  "bt": 0.80, "af": "log",    "at": 0.20},
    "CARROT":     {"base": 35,  "T": 450, "bf": "hinge", "bt": 1.00, "af": "sqrt",   "at": 0.70},
    "TOMATO":     {"base": 60,  "T": 200, "bf": "hinge", "bt": 0.40, "af": "sqrt",   "at": 0.60},
    "STRAWBERRY": {"base": 120, "T": 100, "bf": "sqrt",  "bt": 0.70, "af": "linear", "at": 1.60},
    "MELON":      {"base": 250, "T": 300, "bf": "log",   "bt": 0.20, "af": "sq",     "at": 3.60},
    "EGG":        {"base": 50,  "T": 332, "bf": "hinge", "bt": 0.40, "af": "log",    "at": 0.20},
    "MILK":       {"base": 160, "T": 122, "bf": "sqrt",  "bt": 0.60, "af": "linear", "at": 1.60},
    "WOOL":       {"base": 200, "T": 105, "bf": "log",   "bt": 0.20, "af": "sq",     "at": 3.20},
    "FERTILIZER": {"base": 100, "T": 200, "bf": "linear","bt": 0.40, "af": "linear", "at": 0.40},
}

_TRACE_B85 = (
    'c-rk<O>ZMva{Mnk>mU}XFW)rX+?mE|S`D>&iSa-'
    'f4B$0v7`un@`n1^pZcU3Uvg$=fL}nG$vR8l(0$F^O?>i$iGV|{z|MS=X{M&z@{L9aOKl%4xfBVaye|!4(<kQXP&nJ(kC;##5U;pj'
    '*?;ihgdieEsUq0Nv|K;hShcEZ*!{>fJ*{nZ5Jbm)>$;Z3<haXNJN5A~^;oTp<d^$Njd3U!tIb95Xy8XrJ;eXG~jT^bWdAHuSF=$~'
    'dmu_h%&gO^p&BMuQH)!tj-Iwi;+lEJ<jN1Lfdi{PV+OXr@P`35WcF?$xpMO}dKaEH2-A&Wg{-'
    'fuAM$PS>gCqYmv>%_w;pE5l?cK*wv(Jk{w>F%fr%v5GtnZz+c0YXXC+=mxzV?#?+iGXv;0L6Wc-'
    'd}WkLGi~a&S+#uN^hG?FO8KzKi`o(P(|`#j^l|wzi!|Jq`Ol7I51YIDq?p9{h)vZrjbabEAL!UXIt9)7epTy3_qo!ahI$Cp+D)Ua'
    '{ljPVd)5)3?6ObSL*y(06StLeyEX|G^d&%Y;wzNRIZCc4zxN2eaCUowzjQDdgUd@Iu-'
    'j?02`f>vs>o{9%3n@Zt8uzYYes*f=<V(2b1GB2#Q3|D?AZ+<&U|UXDs<aO0y5UAj2;zj%Lt_bJsHSZMpL{H)C3ZElJ-'
    'x{CZ;$`UL*Y@$|oTa-&UI&?CPwK5)T4=x+I^U|VOqi0LDU87hhYDE(o))*r|+4gOuTiah}Gc-m;6T{|+wr^te-'
    '3v=L?}UQZ`tD`>*^Zgp)IargTY#;F>$dQg%5__s1aIs$kQlvXp<s!v@6+p2L(NEFcJ{{rtR!U?lzE~NyqLJo_li~9Q;e<Yecm^RZ'
    'q4T}<$b>I7!Yo3)k)YTS{+h|)?Vm+6MGG^?K*7By5&sc%W-c^rWm9z%zm8a&@%Q4?dxys?e=}UeW#<{nQvckYE8O*TZlB_(q-'
    'svf^2i#xzytJt*=}PR9zD)1vV4zTxJ}>vXM)dU2bz;y7jhZl<V!%eY<pzc<D~=fPMWc=imG{@w6WL{c(M4Nof4T&HbO${}Vtc+Hv'
    'V?JCdvS=h@Dw_AZKjQV8bvZ`^;>3#3iQKo8oz?DNC@&E~uH{ryjoK^{Eld*0A8YV`p<=gi-'
    'D`0IlSS$~dPeQ<`j_7Su(mR)p$II_vB+D|}_^?0?*i~Hgg`=C`}sDT9NgQhuxT1wi>u-<B3SZ3|63riHI)~5$_j2X-'
    '+;YX8nJX_W`)#d1_OMB8ES#fFUZ}W7tUvPm0jDS~p@qXuxX^05@PSXq9ckStW!X<36P8M|MoN_A&yhd{#0$Xsdo5f_o31aWp4PZx'
    '35WHU+G4_?pHc(c8=2H;2RZ$KJVFO~N=c<>((QCH-C_C=wiXn>LL$0{sGB3yrbSGlH1mc={18pNRC`|Ffzf7Cc*#fOq<&`NSkQ)3'
    '7u>V9QK`15Qq^-OVpyh<35^$Lb+4}G<LR5PCM*oBa^8yY{+h_uAjQx2bl_^(xhWld)66bqtgOS%LGnF8-'
    'k<_V86~L37)4Pc=0Z;%UuS|yAO#NyjV47KdKt~Iqscx6}K7c-'
    'y53Hb`qtQDP5l<NcUnn;p<`%BRZi$RxDZ{bMXmG6E=xVRD8u?Qajkdn1Y@@GC(_q;47<LuYG%`*52!q?0rZZIq(GH!YeWs+L#7qu'
    '28tPRH#)<9}zjs5<Xha0iMIfCZd@P~u5RVj_T3`QhO!lYL#W3>yn8ZaooXqGgZ0Qy^1w^;7R~pVM0>urpQoftaK*mfUKsm~E6TKE'
    '~g0;c+NON5&9~#{5{oJ-ed8CV;HgEYS+`vUfG1AHk8|DQ2DEXqb72ruNj9?`&6N@>R-'
    'Yd~;HUH%8Z|$bCUgSoN9^r*A5LY^<MhX4obJJz}gQH^OI;O%2=>ph*<VaRjMH@YjpRa~<EsR*5>KF~)2W$}iN6ghY((@;dpXrt>='
    '=kWtn#ZtJD%!bX4D5El`q%ux9vbTNBX1I$KA`-'
    'lgHU=5BSO!9mYL=QXMUgOA;$q5ldyo6)J~rErvn_2(7C~y0I#HhTJ0Sdk=BS7E{;y-U2fLcc-A_7b6XDWb~(wjeQ#-'
    'R_oqo22M3b}fiOVae>C<uNJ-'
    '>%tHj}Zt<f!AI8LtgQ)TSOuwb;H3Xu$acLR}tAY%e*#tsY{R*S?#rmnJ0u?sv>)<j2cCS?u;#e5O%C!;-'
    '_@KPY~CRDMy*Bv!XAqfirH4vX;V44J2X7U$DItonBbv(GhE%ETf1Bp+UBVQDHW-'
    '+Ja`wTdgtPuJ7(;*e}K_W5cTn5##J!ZNI)Ymy>1?&K(*87eanD<YBk5)b26AdGs=>3Q919Vz-ofJUSLg7&`%)u!q#ba5XO!E4Epb'
    '<HQdImP*aqp$8saRmKiP#&Ewn(WT{9dEBZ4j$Np$g){>=xv3sJ;$hh3-'
    'iekN%(G%Y0ix&F5jcS}6IELb5D3mNK~1SW#9DUe{D(=hs0i4cZBIrVwj~IkDPO5Pp&+JRQ`Z*-'
    'F}PCt|_K^ORZg9l8e#xq&dwVQGoMc|@IJbX&n(ZIxZmR|SP%3?eAg95eRNvEW{9#y-l2usIwiflM>0OK~o0f!ay-'
    '2X9!?*6=q(midq&fn!21!~X6_q{g-YW-'
    '{{%?mg8R=wu{`ljn)af^e+=N4d~8+#PrnoVGSRK^9TW_jP$gy>M1bJI0EA<_|qEbgG?7t}|0}q`b6@D?5ALvd{tsQ@L)O4aGJS>#'
    '39lc>lC(eFzrPoP8i8$X|eGl`CB0Sn^;lP)NY)#yJzvPsX})i2=ohQlTcoijXI17Az24K}P>EcV)ssz~BsbWdUNugnT6|xQ1mKZ@'
    'mM20Ml`)ptwRD?rIA(+U_N)^?-2D=;{L-'
    'XcIpm;13)m5?{iXuaV~Y@Sj7;V`yC>W~akdDC|OHk#)f_rfwb<Q_Ip1FzTyKL1iIZ!1#$GJFHnRggL(<$+?guXb9DSdWHTxeuY~9'
    '9mlnY!U9Kx|8y*`cEK0@XA)c9#7sFO0IG%_8EAw^#!cCB3=dx?5Rf0RMFU_A8eC0KZp#<kI70m#&sfGW0<ITQHH=v)TZ001o+gN2'
    'ZP$75HjVpXv>id;V?09O6CiFA7EvE~#N0R?u#5$^rCD;?4X<n!OtEfHJ?3}{X4x>U;l1R7OU2$|d6AiK4ltGTB?vteLJQ|imI3!c'
    '`XUi<0i*7H@J?-6enw5nVg*_=2kWeQ6~TguElr)E-'
    'jFk+gquLAG?j9^(~MG^xQjB1TIK~RlJBETio~;v**u#tYB}LkW+^JU!UW)OXnr~h<UB^X1K$V1fXh_n(M6XDM0$i^K><LK727W|a'
    'ZJn!^lKj$vpfuQ#{v>8*?;1=k+X$ECg<0pO<R#|Y9sn;08on*jBH1Fic{4M>LLjS08%O*U<Nvn6|pPnVcHc;00MLk;+q%B;=wmc1'
    '!SHSw-k=Ue*@QgJ5*L6osflA`HrauG-D|+B!vrYB+q_|Ro(G50n6BdCf8@X7W|M$sh&y3`QG}%JUR@2;CGjJbBD+hQ<-'
    'T|AF3<+gUa$O&~zlcOQtG45^uYrc!rAvoMnZF3?MQsoBf2*n;=p!Iv{0CdBECP-dkAeiFZAO@8#V=WBNP-'
    '(~A4D4Bcy7yMSddsZJ(m&?d)fc=*sazG2CKUMyJ(N1Pu@GBwFpK0FgVPcRD%vjjaRR3z#ebX}CK0-'
    'TsYFcxg+a+`2sw&xaAcpd}h3<5om6sQ)G5p)9(5V)e+B{)2i#Q~{c7;1hjal!~geY(7zYMKlJxTr6e+2uL3ZAIg$BiBYkX*O<YM)'
    '2D4Rd`FDPBK)Q7-'
    'JL(6h<GiTBt;J+Yw+fDMfB0W;d9U*~6Q{#ARV2icHbg07z`ZqBmBtKT2U#!?&@l6o5#P4UIGM&DUt%S^pdJFQvj!8IU%~ICR8%IN'
    '2`;5y3}rR=ecJa8gNQXIM#9ZM4xCS%Bg{5{~E>=Vs_SF5fIT7fv3d<M3Kpv5*>6@I(A&LxTdw$z#2O4OQ)txv*iYBS${RToTb)D*'
    '+X#OFSmhC$<(+Xu9#80FN;k)RGvd@LJ>icOlg>EL`lS+o|(gEpH?kGZE>p3IMt5p-'
    'ALwr`@7Nw!5>GRRdfrzC)5}IrM~1;$6CJ7=i>Q@^%B|V-'
    'NxMNB@DxC<o6W>blv0sFu$EYtfk>hH4tFAm73_|8dRVAekoJr(RSm1%lenG0EL+BJg#{#NbC;dzQ3>S&D-'
    'C$59$I&G``OGFbo2(*vB`I=j6){YF*ts6eZzOHFS!x8S|A^4Zt{;XNYel)`r`35_*kj5bcpEeXjsaa=3FU9_%TXfa5L({|X3ZuF)'
    'yTXOl$i5SGA&gVp&zZ{wnx8O~DX~0-0O29Z`X>VdhWR~O-00m<1Ht``fv2R?aaRo9=YcmlJXVB>)3b2<Y8xAak4HR}Ww=9kEQ-IK'
    'S&Z#*9L5wcOHvN-'
    '@S_yvcEYp?>`j)QnPH8%3;Buluv7Lv4aW3>hr(jQhz#OVoGELK_o{5HPWsW?yQ8K;UdB_6%a6{^J$4)7YW905?-'
    'CKKglzE5*>2He~3#(qZjFW|3Hb!L~doX#Zq)|Rxc4}-'
    '3D^*K3iJA1V5j$}NC^NZU+|;S2Q#7g^n5eMq*=T4ey>=jG@)eM^X|OpgFSeM$H#ErWDE*&clyY%-n4*soUM(D?YVI*hNG1WH?-'
    'p+jzY%OONmz1nu}(yNQf7CiVL?{;!YP_w_h(Yi65*NJWX~YIt{b0fB`pssMU+xwF(-+uDFcw5kj2fr>4FP#qnVW@oCKvL_@lNA-'
    'GrZXKr%2bQDxqvwTU=KEpA51qI}yRn-FuIH)nI6(#$Jj@POIWJ{B@EVzEF8anT4f8*JVhvcr~MAZEekWjhI}2G3ZoZh4e=@H5pws'
    'VCB`14NG#Ua3@M0tHF0{g8F$6A%tCMiMu(4VhL6fv+=R>#bddYH2PddJ2W{<%p$|EB75U=n#zlG*~#7yGmB#7^H*FRdsB!m!mr#j'
    'b>^ks*$S%(a;iUPNpzUQ3WxbTXps^2N!&_U@9}AU`aac(@id$<GQ+3<a|vql$HZr(j>w$Vb;(4d6;j>D?#an2L|bFnn+K6xl^|ay'
    '{m_-4!D#Z9u_NALcl^Kg%vK8WahdBNc>b~)DNkY3AU4&h20`-'
    'T1D#;L1ip2Q(Jj+=e<Ga86K=L%~30ZKsN;pYR~J6`OV5P7ViN8Xf3;*VVh`9u>ELrij1{{cocYUthnDgrbo2KO)*v49$N|BV8=cn'
    '=z7^&-'
    'N0hgtGI(ijDl+h0jA6Ok}OGkOF%DJly1u0EB%1utl40+*rDhIJWAsM>e`!U@y)XsB*v_#LVYbn(@6#Sj_+E8rj~?f<v8xeRJl<r_'
    'v2i|Qb@~!P62=hDP=e3Hnhz7sXCkqfM{q2mXk3>zGJGwEdE3oEzN><17k#}DeBA13lrqwjuhcoW`Rml8<%H|cao79%6BEghPlRsz'
    'KteT#Fe(j2r(k~Ye5{O+9}M2<)#4k9I;*?#T*IR4lgfd_V7|+Mw>_rmB{g97H>e1$gT&<9K}2fRy$(6!XvUWN9sFEsp}<qqq$8i$'
    'dQKo1YvVO7#XXI$C{25SS(?}Qfb(7At86;T4|4I2^nRooCgg8crgngB#G{AH`KRCUiw1h%%i3;t>i>JLWZCuMT+j-'
    '*&`2Ga3RSS(9Q-'
    '*Rif82MS*@^7D2yCM25{4eaLdav;)fsx?v8Jgpy<=Q9`+fe8h)a$}9zv_`<7+LH!d}tX3uOkjvP?T6{2UVzw$|Q#Nu*w??7PonKH'
    'zBprjE3Su3oROt2sH8XV}V$5VLIZR{~1LjhjDNjF9axZd35QBuXvPyL+c@EHaD)82%u8wvYCgHSc5mKm7>=vavn?_iRZtE8_DAWN'
    'IHjcFe49yq>-'
    '*eb_(cHwW<~Ze}h3OldWUE@`^fOzV>w*qY#_Rh=Fnv*isU1T8$_S<=)qD2DI<Z78m@=OAGmPUTuT$*|ChIhjA!cnQ@SLCd%g`8u$'
    '5@M>Bma&XJtr?~DbZ=2=)=;_w*XjN#XP_&%t)`5d{d2Qsafgbl(~4AOzl6tVo|UzI)eHY<!pSW3C$+BE3G*T(SnEYR*o>-'
    'c%%C6P(hXzx`Nu?EL6=0O;(vqUS^&c5nvS(iwhuZ1wpuFFqf|GLL`d`w{~_^8kp(lMZtaa=EEwSq>H0_$&xvNBAJP5l!?|M))RN7'
    'H({bHJbw(sYk`#qXnP~dreTETQkgl4{373`doj!-'
    'JJlHACLB`eQe@wGy(Cn|C4cR1M}tZ7O`MJ?I0^dL{OnsJ&6G95wA8x6702_YGG&2fNIeP|MkOQ<4<uS`%g<_=@>rtN)S6Nbm?A|C'
    '^#UOer#2*UqgDzTx<{}_Jrj;pTAwZv1N${FMW=UVoalD+DjAr}K!@p>XsO+W+lSynl#Uygf+k-'
    ';NJv9fUc2T&fNj98V7~GYJ%pZ#gnlbET`fn7)}KNH)JGx)Lih%UB^C|Rxkz0?byvLDEL)p3UNl=z<oRC5P{y&kOv>>pG-'
    '00~W>tjDus3sqU>2X8QjXJd{Am_^gwBoeA~LDqVy{SO%f!u-U4v{{JY#RG546QXT$$ct9}6`$_I~cy5&P)Y*oc9gkw3@5o-'
    'Y#~nXzm80iDeGafDz=26I_)MmsZW<T5HDPlz)ESy(=xOxU0%ka<N%5_xvaaFO+76iNXJ^DF@-'
    'CL;Y#OBxHVpI`}~AjN1^81bWNL;#c3jAir4(8_<9^>B(4D1s$&Wb#%LKbsOo2zHnw#Xo*k8Ip0wj`>u2u|8uMC*RX(85@Xd-'
    'I<U#wh`dOMTkJ<1yU5yRy3T$os=TttmD>UB~)ApJ`+YN5Dzzf@S<%%-'
    'Df<U%`5W(22xQ~*Nz>=OlP3Oo!jDuu2}NgVzg+6Q^T5v8IgEg2TQ;^r$AHz#b=}(R_L-GP2=k((;A538#p{sUDteUW&4vC;L}$9h'
    '>7BB^Pn_jy|a|W)RLLU`P>34TEnBkj$W=<85hWsg_e?j%Ac!razo@^iMnIamG<~CZ%886&PMnf=@tz=Rk&z8nr%OGr!jdnR#52W6'
    's#q3&6^bmX;M#`P0~%V8!q68(5C!yNp`m#m?XK59Qv(OASucK3=?Yb;&s$n%k*IC7RYGF%xBh~7P5#2gS~nh;VIg7zI22;1tfB?4'
    '3IJCe73OAswa@(vjC5y^fT%VOw_QGNjI8EO5xi_oH}KRz&%pVLDl(ygEzBK(MhQjK`940PmG$Z^I?{u<o70L$yyQ#kSKyZSiQ{oG'
    '2{PRSLHN*toY4Kg<|sbtjdSy61Zl<hdy;Z<y@Q}9Wt0GnRhZMX0Bv*c0ETk*Blu1QnnaYMgp9>$}7qsSH)+eFepozVWf^@NIQuTK'
    '_(~Wtzf=I&{QFLjGqm-nDoiL7~QleR=GiH)c~4^um|`;NnUI&QAX+lvWRD9**aS**Wqg<lGLKJyLBKW5|O!L)edNj7=W)#tBJVYd'
    '`lDasCudJc-~agq(oQKZny{w(~Esc*9ZiA-ONH%cKYX_J-Td$#AXF3TI+=%g92Rdny*Mb4<58xur*{&YAlU8%iR;5@^Ip4svKdOr'
    '@3T9vg%uC<co$zx={}=oR5_`z@^7c9Z~bd4Eo5Frq&3y^D#mO0TeW#_Qt3&u}N3uP@b;cF-'
    '!dgZn+4lw`U4=7*(;Dcc=X%pI?%|eO%~(C$>;?0j&Ujatmc{ATgLJvw=IHgl&l3Bu!CcE7_N@q9iUaheS$%zFRj-KvS>|rR94&a&'
    'Gz#q@!z=rf+WYDu?>v$#$j{YKUl06y=4<)?3Kei}R|d@_0rA{b2W{L+%4yc#}iQE@9|<Ajzb~j1kxzBzzNBa6X@?j>M(zCTeF-lQ'
    'bh=8i$8AMKP=akpW-'
    'I!$q=yL&oyB{NvQIqHKrOqi;F_OI~NwJ=sD%YU&v0))AWURSXCr=Ws<e=S$92+^9^6vJP9pYAExayQhc8#>vyGm~zbZ(RP#u)|94'
    'JDF;bp3_;n`<`Wh2PNa7Eh|tDDbA$P15^Kd3g|6Hhjai5l-'
    'Pha`0MN1xhXgstPBg;TUi*oiiJv7jW$O@;z?;W;n1M)ZIIVWJ(%q@j)gl&m@J#2wFi&P@n>_E2B5zhga<B#|do_&4Nl@R?B`k7ht'
    '$p!O8Ts@A1dmEi8*=yR99;k;_?P%P*w%J2S9nPI<{Ea+vG342kvF(ePtQvSN|&q7?V4M&`Pf<pR#LC#Mbo1nCJ^>0(IuHcI`g2Tv'
    'Dwx?KdlOzI7xk<2*bK?UCG#e#x}H_-QL?)i5%f}01&mTq|%Q0nWMQSfWFJH6|;W0HZsc^+g><SNu~}B&RBXS=y;WYb;N^WrqakmV'
    '^*-'
    '*VUJ`}Qn1j%)<(c#vxo1e7w}7s8elECY#Oi9Avd`tt1xFqj@&+eK>~}l$4Y=@3a43#^i_UQla%K=Or@pF%n;jNbxz`^A=lKmY1BB'
    'OLOFN2<EAr29-leKINy8xdZZqHc=4LlZc#u$mPTP$21z~=g{ww!cs4gBTie5MYU`A|rqq>c9;(_&B8Rgb%WsxK$?-'
    'qh;&5!KLaJY_GBGow(yNcj7pm?)QVrIRpQV^2EQvRNqOwsyd!PjZDK9)|xs-rO4Wkv7dg^UCU#dzX98)SM!LAp7*-'
    'zWFi1QesrizTgVjpB_)8!X_B=7pxb?OKcW(bOh8Orn8z@!UX2-'
    'x(gV0mY1Ug8362pwfCEj2aLQ6%82RGIvQX!BMJh!{67Q5yX83Nm=zo=~g4w2H=uZsH2-'
    'wc;J%H<())En$LVZlCCKP5339JpBGnaI?Hqs|6@B7^xy81Wqd+%$gE!j<k8gBr7`ECa5Q*;>z|4#)?I<E<<FuD5OAyVWo%c@--'
    'd2g{bZ6whj6sW=S7^RH|YWk`=rZs~of>^BpPTH*+%Sps~a@S{otdFp}OYOd=(*RWzsIuT&rl(a{?>rJ3m-'
    '5s}AWDf2+>jLS@#bn?Qfg-jMJ`AVlbW8=gQ7iAr`-'
    '2DO1j>bP%OJBKhGJXzA(G8Vuxv~N)x%|T$J{QyCxdxRIj%R_*O^R|WseUQ3QsttRO^OO$H`;Pb>BfyF3NE~C67EE}kbvN7?5l;fd'
    '?%otr7j&}XO!2rW5akm6AY!Bb^fxmomNg1Am@ksv7L!J5wSJ3l5WL~Y9lwg=!cIX9Ea4#DWkZtkIA$JgX!Z|%2ea2dBjQAABbz(m'
    '%_1Tl}N-GZ3Tt`(b)irF8Yr^LYB64TM+Z~{I!q=yr8Y8VEG0_E=EfltNolb*h$ey^Xc~H-'
    'THSw!`<EO)|s&T=*JJYf813)>stkn8-gZ&=1ctS896^}|MSEB&E~uH{ryjo;ILDM;D;}pD*2)NW&z%E$wWwt-'
    'oC9Yf9_?SEvfqF@gGle{N>l*{_D?w`zp!Pwe(>}YT5ns-It$!x%v3v$D5}G_H^THww?X`<IlevVV<UbeS7!u<n&_n@pfFle*AfTd'
    '%OQ=(SEc<Pd$D1+~TMEyZ2w-'
    'J&YPnh}bW)xXCVRDf5%hKdjfE_>Y!*(c^~}+2MHl&X99BVcQmmuj!u!f`i8w;p1J~g^rG;kRObO804wH==d*IXccFFA>RSVT)bkm'
    'iKAIYkEtbl_;mj_Zha{A(5cSWyjUIjYx>Y)@DP-Lc%(<)<OUDT$Q;}8+Ie~R7<8D9ko;N>SAXHk>E8a}-'
    'Oc^|T|7y6ya$6R1|BZP(_rPsXR<ZmeXEBzBRmR+&z(P}Hq+H3-hStglc(5yD3&W;Bx>7%Ntt248N<H{m(n67L9^-'
    '5ZeL;zWq5;ZzdO{vJN&zY>vQ-;eCm-&=z^66Re<Fp*k7}qlfFi_G#asVwBk(?-'
    'PZMUwIhpCy!m35dAXcJRbcAPlq;!w^iL||7J7!!@woNvWH3Tfg98WPMOvG6zIKn__~GSD2j*qGYj1BpzCZCUWu;~vo}#M=AGW<eB'
    'X2(k`miyr=%}4?LZlYcwVGiAkX6=CZJp*@^AT$L@kW@d+|XaOADz#%xr|+QQQInAb@vT4tgqI=tFTMwpaboN&Gxgcl7E$C(WzCDl'
    '|X7GLI+XrYNacG5s3ZLFKWIOny-Q#*gkc6gjH`Z`@<u5&aJ#i8f2DIi7eP;mPK0*Qn^-'
    'vkvMt#EIn(mJJA=9lW_2o*lsf5>+s9V;)3atOO_sxH4)Cl@0`EZvJ#nF$j-'
    'Gr8cVeWLnts5XmLS|RQ)SPsxDZoOW1g%SuP&~(*rbqbeBOhWF>UPm9VV+uK2TSz3%#sLyS<hMq6L=i*9_J@9`-+&L-'
    'Z&%)UGEwW#6q+O&4vah5~%_=0Qb0_dLCSRZXa?9Ot~WpxeBb60#FGfX+cDi`DJ5_brgESBeLku2jy(urkz+8m3APQ!=0A8#J+umj'
    'F-SsLV@Cu}%}kJ6Ys*xToP337epj2;YJ4@QH&$eU}AwEK#0JAZlYw(8?vnEvk_&&D%6=%>3E{%%#o&>@E*#WGk?*DL(VRj@nGbLO'
    'B`6>P2w?@8|Sv+}(cHh7wGN-mFaC1=SQ3vi1qlbiB1aG06<6ro_meOYELkty2CMdc)l`|<T!yY$?XjiSq(r|qLrJC_hQwK~J$mIl'
    '_v+$I<*1J5tGlpB2>TM!V<k)U&sk~Vg4Ejmb144#rp^FYz8T|4cHiPi9=GtYJc3>IqMiH|i`%96>P(~adSHqgnbTNJd-'
    '%Nf@AAsm?`n6=&#jKao*Hv|b+@Zc}&t`pSWECp<Tc%|r@oqHdkCxVrjTW(kM_I>_@g0b`2*5olvx-'
    'A}_ZnHAZxWilXJhY0Ozc7A^CG_;I^8)|kRJz9xS!a?Ae=RQ9hTk)Ic9~=S5$0ZYn=M~j<C((;a=1pWl1TfMwGuw7&ztb+(HWNC1&'
    'hlG3jdC`+od|wK0VNupBHWA%<0a|EnR*aY4i$hTL?(HNA+2>pIhsy=Q%iR@4~$=4Mop1HyAC|HuaUer$ds`SIHJB=&(|XpY!4rc_'
    'jIp@I7bwIl;{oepKq?DJFC<T5^juxygN%`1P*mWbY-'
    '1MZi#TV?;+z?2Ibh;g@A!uCWRSUv$$kpx<7XBd;ya6%kYb>0vYY^0EP?=QfL9KgkENyY!cFSI9Ts1syMApfF!r@d{Dwk0<yg5r|&'
    '4&WjpUkzDAj`G8^<zk^ywXE087$1+YLzDt!Me|~&QTz|BN#4LR$uJ9GoCC-Wt@Y_%;yU$J|tB^dib~cJLzFD%+v$9!=Y?MoHq3=%'
    '4%Nh17>JumKl;UFyLk7CowjZ{3i*BWcQCRDYX1dU4oAdv5t1v`hs6tk>=<ac<iB{Zek+(V~D8=81$pCnE(WPNfX`9pN!+}Is-_HA'
    'HZ^*9LUfH6*a)ysYe_m8z-'
    'O@F5wei!ft$x(9r(UkCtRybR9<q_=31xD~0Xf3K(jP|jvI}fh_J`;CF@Mj%v>d6h{f_dQhqqNp!=1o`il~Cda#(cyM2{VVi6kq@9'
    '4?EB*O%`0!R>H8EhZ;VVQ)mciV*nu#K4C%3h9#6j(i>&5lHB>yE>B9BCjwVgROWPL9di}HHEa&)^w_uu%|527oXp><?g(gzGXwA%'
    'V0?@j&P<N$(50TYCAU(C+3^n1pDdb4E}i#K5$6alGfLVX?C5{%^Hj1`upz@^2rfALmOJq-z<Q-'
    'c=VI&9O|qJc1`&wpz$ovoD25?d+Gx3X~h48(KU<n*oT~cIx>_k&(zNt2};tR!jH~HIIu?<oILH`;d~JyDMhPIr|U`Bey%4u73;9T'
    'a-1B#W4KPwW)X2|p0+W^C353NGBp`yg*xHAIk1ASR8&`@b!Y~Cxt%4jL6-7(1=DtrE9D%Ia5WwQLe6W`jnMjjgLp;9j|yNmw-'
    'R(q7EQb~4Xw%yvoun@n&!MD<*Cag{aHP}n)~HiSRu)&ztt_`rL<TGV&9>&BC?*s;1vA%m0+DI%R4X|EV=T$T`L!lk(3&6ft|D+mN'
    'QGx$eoTl&<65wVkSz>dFFivVC(7(4b#$EBZmjp<KsX67fdy#p#'
)

_TRACE = json.loads(zlib.decompress(base64.b85decode(_TRACE_B85)).decode("utf-8"))
UNIT_TRACE = _TRACE["units"]
MARKET_TRACE = _TRACE["markets"]
del _TRACE, _TRACE_B85
