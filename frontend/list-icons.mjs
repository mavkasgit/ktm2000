import * as L from 'lucide-react';
const names = Object.keys(L).filter(k => typeof L[k] === 'function' && k !== 'createLucideIcon');
console.log(names.sort().join('\n'));
