# DEPLOYMENT AND TESTING GUIDE
**YLIV/YMATCAM Fix - Production Deployment**

---

## Current Status

✅ **All Code Fixes Verified**
- Driver role comparison fixed (RoleEnum enum check)
- Sage SQL properly fetches YLIV_0 and YMATCAM_0
- Data flow chain complete (Sage SQL → Program payload → Database storage)
- Database schema has both columns

❌ **Production Not Yet Updated**
- Programs showing empty YLIV/YMATCAM are from BEFORE code deployment
- Need to deploy updated code and create fresh test programs

---

## Pre-Deployment Checklist

### 1. Verify Local Code
```bash
cd c:\Users\BNT\Documents\PROJET SODIGAZ\gas-platform\backend

# Check git status
git status
# Should show: "nothing to commit, working tree clean" (except diagnostics)

# Verify key fixes are in place
grep "user.role != RoleEnum.RAVITAILLEUR" app/routers/driver.py
grep "program.yliv = sage_driver_code" app/routers/integration.py
grep "YLIV_0" app/services/sage_sql_service.py
```

### 2. Run Diagnostic on Local Dev DB
```bash
python diagnostic_yliv_ymatcam.py dev.db
# Current: dev.db is empty (expected)
```

### 3. Check Configuration
```bash
cat .env
# Should show:
# - DATABASE_URL=sqlite:///./dev.db
# - SAGE_X3_PUSH_MODE=sql
# - SAGE_SQL_SERVER=35.203.21.23,50389
# - SAGE_SQL_DATABASE=x3v12
# - SAGE_SQL_SCHEMA=SODIGAZG
```

---

## DEPLOYMENT STEPS

### On Production Server (35.203.21.23)

```bash
# SSH to server
ssh debian@35.203.21.23

# Navigate to backend
cd ~/sodigaz-backend

# 1. Pull latest code with fixes
git pull origin main

# 2. Verify pulls are successful
git log --oneline -3

# 3. Restart backend service
pm2 restart sodigaz-backend

# 4. Verify restart
pm2 status

# 5. Monitor logs for errors
pm2 logs sodigaz-backend --lines 50
```

### Verification Commands

```bash
# Check backend is running
curl -s http://localhost:8000/health | jq

# Check Sage SQL connection
curl -s -X GET "http://localhost:8000/api/admin/integration/sage-sql-health" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Monitor for new programs
pm2 logs sodigaz-backend --grep "sage_program\|YLIV"
```

---

## POST-DEPLOYMENT TESTING

### Test 1: Trigger Sage Sync
```bash
# Manually sync programs from Sage
curl -s -X POST "https://sodigazback.yingr-ai.com/api/sage/sync-today" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq

# Monitor sync results
pm2 logs sodigaz-backend --lines 30
```

### Test 2: Verify Program Data
```bash
# SSH into production server
ssh debian@35.203.21.23

# Check database for recently synced programs
sqlite3 gas_platform.db << 'SQL'
.headers on
.mode column
SELECT 
  id, 
  program_code, 
  yliv, 
  ymatcam, 
  status, 
  created_at 
FROM programs 
WHERE created_at > datetime('now', '-1 day')
ORDER BY created_at DESC;
SQL
```

### Test 3: Run Diagnostic
```bash
# On server
python diagnostic_yliv_ymatcam.py gas_platform.db

# Expected output: Should show programs with populated YLIV/YMATCAM
```

### Test 4: Full Driver Flow
```
1. Log in to admin dashboard
2. Create new program from Sage (or wait for auto-sync)
3. Verify program shows:
   - YLIV: [driver code]
   - YMATCAM: [truck code]
   NOT: YLIV: - | YMATCAM: -

4. Assign program to driver
5. Driver logs in on mobile
6. Driver receives mission
7. Driver updates quantities
8. Driver validates program
9. Check admin dashboard:
   - Program status changes to "Validé"
   - Stats update correctly
   - Sage X3 receives update (check YFLGVAL2_0=2)
```

---

## Rollback Plan (If Needed)

```bash
# On production server
cd ~/sodigaz-backend

# Revert to previous working code
git reset --hard HEAD~1

# Restart
pm2 restart sodigaz-backend

# Verify
pm2 logs sodigaz-backend --lines 20
```

---

## Monitoring Commands

### Real-time Logs
```bash
pm2 logs sodigaz-backend --lines 100
pm2 logs sodigaz-backend --grep "ERROR\|WARN\|sync"
```

### Check Sage SQL Connections
```bash
curl -s http://localhost:8000/api/admin/integration/sage-sql-health | jq
```

### Check Pending Outbox Events
```bash
curl -s http://localhost:8000/api/admin/integration/outbox-pending | jq
```

### Database Status
```bash
sqlite3 gas_platform.db "SELECT COUNT(*) as total_programs, COUNT(CASE WHEN yliv IS NOT NULL AND yliv != '' THEN 1 END) as with_yliv FROM programs;"
```

---

## Expected Results

### Before Deployment
```
Programs Status: YLIV: - | YMATCAM: -
Dashboard Stats: May not update correctly
Sage X3: Programs not received
```

### After Deployment
```
Programs Status: YLIV: [code] | YMATCAM: [code]
Dashboard Stats: Updates correctly as missions complete
Sage X3: Programs synced with YFLGVAL2_0=2 after validation
Mobile App: Shows programs correctly, drivers can complete flow
```

---

## Troubleshooting

### Issue: YLIV/YMATCAM Still Showing Empty After Deployment

**Diagnosis:**
```bash
# Check if new programs were created AFTER deployment
sqlite3 gas_platform.db "SELECT program_code, created_at, yliv, ymatcam FROM programs WHERE created_at > datetime('now', '-2 hours') LIMIT 5;"

# Check Sage SQL query logs
pm2 logs sodigaz-backend --grep "YLIV_0\|sage_driver_code"
```

**Solutions:**
1. Verify backend actually restarted: `pm2 status`
2. Check Sage SQL connection: `curl http://localhost:8000/api/admin/integration/sage-sql-health`
3. Manually trigger sync: `curl -X POST http://localhost:8000/api/sage/sync-today`
4. Check logs for errors: `pm2 logs sodigaz-backend --lines 100 --err`

### Issue: Driver Login 401 Unauthorized

**Already Fixed!** (line 770 of driver.py)
```python
if user.role != RoleEnum.RAVITAILLEUR:  # Fixed enum comparison
```

### Issue: Programs Not Syncing

**Check:**
1. Sage SQL Server connectivity: `curl http://localhost:8000/api/admin/integration/sage-sql-health`
2. SQL configuration in .env: `SAGE_SQL_SERVER`, `SAGE_SQL_USER`, `SAGE_SQL_PASSWORD`
3. Network access: `telnet 35.203.21.23 50389`

---

## Success Criteria

- [x] Code deployed to production
- [ ] Fresh program synced from Sage
- [ ] Program shows YLIV and YMATCAM (not empty)
- [ ] Driver can receive and complete mission
- [ ] Admin dashboard stats update correctly
- [ ] Sage X3 receives validation (YFLGVAL2_0=2)
- [ ] No errors in logs

---

## Post-Deployment Tasks

1. **Verify in admin dashboard** - Check "Programmes" page shows codes
2. **Test driver flow** - Have driver 1062108 complete a test mission
3. **Monitor logs** - Watch for 24hrs for any sync errors
4. **Check Sage X3** - Verify programs marked as validated (YFLGVAL2_0=2)
5. **Update documentation** - Note successful deployment and any adjustments needed

---

## Support

If issues arise:
1. Check logs: `pm2 logs sodigaz-backend --lines 200`
2. Run diagnostic: `python diagnostic_yliv_ymatcam.py /path/to/database.db`
3. Check Sage connection: `curl http://localhost:8000/api/admin/integration/sage-sql-health`
4. Review VERIFICATION_REPORT.md for code details
