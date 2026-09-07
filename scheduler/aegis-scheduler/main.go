package main

import (
	"fmt"
	"math/rand"
	"os"
	"time"

	"github.com/aegis-project/aegis-scheduler/pkg/plugins/aegis"
	"k8s.io/kubernetes/cmd/kube-scheduler/app"
)

func main() {
	rand.Seed(time.Now().UnixNano())
	
	command := app.NewSchedulerCommand(
		app.WithPlugin(aegis.Name, aegis.New),
	)
	
	if err := command.Execute(); err != nil {
		fmt.Fprintf(os.Stderr, "Error running scheduler: %v\n", err)
		os.Exit(1)
	}
}
