import {describe,it,expect} from 'vitest';
import {changesFor,Row} from './api';
const row:Row={id:1,key:'TOKEN',value:null,type:'string',secret:true,description:''};
describe('staged edit diff',()=>{
 it('does not accidentally replace an unchanged secret',()=>{
  expect(changesFor([row],{'1':{...row,description:'Used by billing'}},new Set())).toEqual([{op:'put',key:'TOKEN',description:'Used by billing'}]);
 });
 it('sends an explicitly typed empty secret',()=>{
  expect(changesFor([row],{'1':{...row,value:''}},new Set())).toEqual([{op:'put',key:'TOKEN',value:''}]);
 });
 it('does not save an unchanged draft',()=>{
  expect(changesFor([row],{'1':{...row}},new Set())).toEqual([]);
 });
 it('deletes an existing row without sending secret data',()=>{
  expect(changesFor([row],{},new Set(['1']))).toEqual([{op:'delete',key:'TOKEN'}]);
 });
 it('does not send a deletion for an unsaved new row',()=>{
  expect(changesFor([{...row,fresh:true}],{},new Set(['1']))).toEqual([]);
 });
});
