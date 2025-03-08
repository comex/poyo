while true do
    console.log('pre get')
    resp = comm.httpGet('http://127.0.0.1:25192/test')
    console.log('post get' .. resp)
end
--counter = 1
--event.onframeend(function()
--    if counter < 5 then
--        comm.httpGet('http://127.0.0.1:25192/test')
--    end
--    counter = counter + 1
--end)
