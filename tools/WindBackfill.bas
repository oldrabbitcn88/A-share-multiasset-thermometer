Attribute VB_Name = "WindBackfill"
' Thermometer backfill via Wind VBA API (vba_edb / vba_wsd).
' Requires: Wind terminal logged in; VBA editor > Tools > References > tick "WindVBA".
' Run macro: RunBackfill. Each series goes to its own sheet: column A date, column B value.
Option Explicit

Const START_DATE As String = "2021-11-01"
Const END_DATE As String = ""   ' empty = today

Public Sub RunBackfill()
    Dim r As Long
    r = vba_start
    If Not vba_IsConnected Then
        MsgBox "WindVBA not connected, code " & r & ". Log in to Wind terminal and tick WindVBA in Tools > References."
        Exit Sub
    End If
    Application.ScreenUpdating = False

    FetchEdb "y10", "M0048271"
    FetchEdb "omo7d", "M0041371"
    FetchEdb "cdb3", "M1005175"
    FetchEdb "mtn_aaa3", "M1002841"
    FetchEdb "mtn_aap3", "M1002877"
    FetchWsd "pe", "881001.WI", "pe_ttm"
    FetchWsd "dy", "000300.SH", "dividendyield2"

    Application.ScreenUpdating = True
    vba_end
    Worksheets("log").Activate
    MsgBox "Done. Check sheet 'log', then save as .xlsx and send it back."
End Sub

Private Sub FetchEdb(ByVal sheetName As String, ByVal code As String)
    Dim d As Variant, codes As Variant, fields As Variant, times As Variant, ec As Long
    d = vba_edb(code, START_DATE, END_DATE, "Fill=Blank", codes, fields, times, ec)
    WriteSeries sheetName, code, d, times, ec
End Sub

Private Sub FetchWsd(ByVal sheetName As String, ByVal code As String, ByVal field As String)
    Dim d As Variant, codes As Variant, fields As Variant, times As Variant, ec As Long
    d = vba_wsd(code, field, START_DATE, END_DATE, "Days=Trading;Fill=Blank", codes, fields, times, ec)
    WriteSeries sheetName, code & " " & field, d, times, ec
End Sub

Private Sub WriteSeries(ByVal sheetName As String, ByVal desc As String, d As Variant, times As Variant, ByVal ec As Long)
    Dim ws As Worksheet, n As Long, i As Long, t0 As Long, v As Variant, msg As String
    Set ws = GetSheet(sheetName)
    ws.Cells.Clear
    ws.Range("A1").Value = "date"
    ws.Range("B1").Value = "value"
    ws.Range("D1").Value = desc
    If ec <> 0 Then
        msg = "error " & ec & ": " & vba_getErrorMsg(ec)
        ws.Range("D2").Value = msg
        LogLine sheetName, desc, 0, msg
        Exit Sub
    End If
    If Not IsArray(times) Then
        LogLine sheetName, desc, 0, "no dates returned"
        Exit Sub
    End If
    t0 = LBound(times)
    n = 0
    For i = t0 To UBound(times)
        v = CellValue(d, i - t0)
        ws.Cells(n + 2, 1).Value = CDate(times(i))
        If Not IsEmpty(v) Then ws.Cells(n + 2, 2).Value = v
        n = n + 1
    Next i
    ws.Columns(1).NumberFormat = "yyyy-mm-dd"
    LogLine sheetName, desc, n, "ok"
End Sub

' Returns the k-th value of the result, whether it is 3-D (field, code, date), 2-D or 1-D.
Private Function CellValue(d As Variant, ByVal k As Long) As Variant
    On Error GoTo try2
    CellValue = d(LBound(d, 1), LBound(d, 2), LBound(d, 3) + k)
    Exit Function
try2:
    Resume try2b
try2b:
    On Error GoTo try1
    CellValue = d(LBound(d, 1), LBound(d, 2) + k)
    Exit Function
try1:
    Resume try1b
try1b:
    On Error GoTo none
    CellValue = d(LBound(d, 1) + k)
    Exit Function
none:
    CellValue = Empty
End Function

Private Function GetSheet(ByVal name As String) As Worksheet
    On Error Resume Next
    Set GetSheet = ThisWorkbook.Worksheets(name)
    On Error GoTo 0
    If GetSheet Is Nothing Then
        Set GetSheet = ThisWorkbook.Worksheets.Add(After:=ThisWorkbook.Worksheets(ThisWorkbook.Worksheets.Count))
        GetSheet.name = name
    End If
End Function

Private Sub LogLine(ByVal sheetName As String, ByVal desc As String, ByVal n As Long, ByVal status As String)
    Dim ws As Worksheet, r As Long
    Set ws = GetSheet("log")
    If ws.Range("A1").Value = "" Then ws.Range("A1:D1").Value = Array("sheet", "series", "rows", "status")
    r = ws.Cells(ws.Rows.Count, 1).End(xlUp).Row + 1
    ws.Cells(r, 1).Value = sheetName
    ws.Cells(r, 2).Value = desc
    ws.Cells(r, 3).Value = n
    ws.Cells(r, 4).Value = status
End Sub
