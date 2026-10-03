function a(p,r){const t=p.split(`
`),l=r.split(`
`),o=Array.from({length:t.length+1},()=>new Array(l.length+1).fill(0));for(let h=t.length-1;h>=0;h--)for(let s=l.length-1;s>=0;s--)o[h][s]=t[h]===l[s]?o[h+1][s+1]+1:Math.max(o[h+1][s],o[h][s+1]);const i=[];let e=0,n=0;for(;e<t.length&&n<l.length;)t[e]===l[n]?(i.push({op:"same",text:t[e]}),e++,n++):o[e+1][n]>=o[e][n+1]?i.push({op:"del",text:t[e++]}):i.push({op:"add",text:l[n++]});for(;e<t.length;)i.push({op:"del",text:t[e++]});for(;n<l.length;)i.push({op:"add",text:l[n++]});return i}export{a as l};
