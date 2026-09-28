#!/bin/bash
echo "========================================"
echo "AEGIS 10-PHASE VERIFICATION"
echo "========================================"

fail_count=0

for i in {01..10}; do
  # find the directory
  phase_dir=$(ls -d phases/phase-${i}-* 2>/dev/null)
  num=$(echo $i | sed 's/^0*//')
  
  if [ -n "$phase_dir" ] && [ -f "$phase_dir/verify.sh" ]; then
    bash "$phase_dir/verify.sh" > /dev/null
    if [ $? -eq 0 ]; then
      echo "Phase $num ........ PASS"
    else
      echo "Phase $num ........ FAIL"
      fail_count=$((fail_count + 1))
    fi
  else
    echo "Phase $num ........ FAIL (missing verify.sh)"
    fail_count=$((fail_count + 1))
  fi
done

echo ""
echo "========================================"
if [ $fail_count -eq 0 ]; then
  echo "ALL 10 PHASES COMPLETE"
else
  echo "$fail_count PHASES FAILED"
fi
echo "========================================"
